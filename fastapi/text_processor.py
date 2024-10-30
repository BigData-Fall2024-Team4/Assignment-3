from typing import List, Dict, Any
import numpy as np
from langchain.text_splitter import RecursiveCharacterTextSplitter
from pinecone import Pinecone, PodSpec
from openai import OpenAI
import os
from dotenv import load_dotenv
import logging
from tqdm import tqdm
import time
import json

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TextProcessor:
    def __init__(self):
        """Initialize the text processor with necessary clients and configurations"""
        # Initialize NVIDIA embeddings client
        self.embeddings_client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=os.getenv('NVIDIA_API_KEY')
        )
        
        # Initialize Pinecone
        self.pc = Pinecone(
            api_key=os.getenv('PINECONE_API_KEY'),
            environment="gcp-starter"
        )
        
        # Get or create Pinecone index
        self.index_name = "pdf-embeddings"
        self.create_pinecone_index()
        
        # Get Pinecone index
        self.index = self.pc.Index(self.index_name)

        # Initialize text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=50,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    def create_pinecone_index(self) -> None:
        """Create Pinecone index if it doesn't exist"""
        try:
            # Check if index exists
            existing_indexes = self.pc.list_indexes().names()
            if self.index_name not in existing_indexes:
                # Create the index for gcp-starter environment
                self.pc.create_index(
                    name=self.index_name,
                    dimension=1024,  # E5 model dimension
                    metric='cosine',
                    spec=PodSpec(
                        environment="gcp-starter",
                        pod_type="starter"
                    )
                )
                logger.info(f"Created new Pinecone index: {self.index_name}")
            else:
                logger.info(f"Using existing Pinecone index: {self.index_name}")
                
        except Exception as e:
            logger.error(f"Error creating/checking Pinecone index: {str(e)}")
            raise

    def chunk_text(self, text: str) -> List[str]:
        """Split text into chunks"""
        try:
            chunks = self.text_splitter.split_text(text)
            logger.info(f"Split text into {len(chunks)} chunks")
            return chunks
        except Exception as e:
            logger.error(f"Error splitting text: {str(e)}")
            raise

    def create_embedding(self, text: str, input_type: str = 'passage') -> List[float]:
        """Create embedding for a single text chunk"""
        try:
            response = self.embeddings_client.embeddings.create(
                input=[text],
                model="nvidia/nv-embedqa-e5-v5",
                encoding_format="float",
                extra_body={
                    "input_type": input_type,
                    "truncate": "NONE"
                }
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error creating embedding: {str(e)}")
            raise

    def process_nodes_and_store(self, nodes: List[Dict], pdf_id: str) -> None:
        """Process PDF nodes and store in Pinecone with complete information"""
        try:
            vectors = []
            for node_idx, node in enumerate(nodes):
                # Log the node structure
                logger.info(f"Processing node {node_idx}: {json.dumps(node, indent=2)}")
                
                # Get the content and metadata, with explicit logging
                content = node.get('content', '')
                page_num = node.get('page_num')
                image_path = node.get('image_path')
                
                logger.info(f"Node {node_idx} metadata:")
                logger.info(f"- page_num: {page_num}")
                logger.info(f"- image_path: {image_path}")
                
                # Split content into chunks
                chunks = self.text_splitter.split_text(content)
                logger.info(f"Split into {len(chunks)} chunks")
                
                for chunk_idx, chunk in enumerate(chunks):
                    # Create embedding for the chunk
                    embedding = self.create_embedding(chunk, input_type='passage')
                    
                    # Create structured node information
                    node_info = {
                        "page_num": page_num if page_num is not None else "",
                        "image_path": image_path if image_path is not None else "",
                        "content": chunk
                    }
                    
                    # Log the node_info being stored
                    logger.info(f"Storing node_info for chunk {chunk_idx}: {json.dumps(node_info, indent=2)}")
                    
                    # Convert node info to JSON string
                    node_info_str = json.dumps(node_info)
                    
                    # Prepare metadata
                    metadata = {
                        "pdf_id": pdf_id,
                        "chunk_index": chunk_idx,
                        "node_index": node_idx,
                        "text": node_info_str  # Store structured info as JSON string
                    }
                    
                    # Prepare vector
                    vector_id = f"{pdf_id}_node{node_idx}_chunk{chunk_idx}"
                    vectors.append((vector_id, embedding, metadata))
                    
                    # Process in batches of 50
                    if len(vectors) >= 50:
                        self.index.upsert(vectors=vectors)
                        vectors = []
                        time.sleep(0.5)  # Rate limiting
                
                # Upsert any remaining vectors
                if vectors:
                    self.index.upsert(vectors=vectors)
                
            logger.info(f"Successfully processed and stored nodes for PDF {pdf_id}")
            
        except Exception as e:
            logger.error(f"Error in process_nodes_and_store: {str(e)}")
            logger.error(f"Exception details: {str(e.__dict__)}")
            raise

    def search_similar(self, query: str, top_k: int = 5, filter_condition: dict = None) -> List[Dict]:
        """Search for similar text with optional filtering"""
        try:
            # Create query embedding
            query_embedding = self.create_embedding(query, input_type='query')
            
            # Search Pinecone
            results = self.index.query(
                vector=query_embedding,
                top_k=top_k,
                filter=filter_condition,
                include_metadata=True
            )
            
            # Format results to include structured node information
            formatted_results = []
            for match in results.matches:
                try:
                    # Parse the stored JSON string back into a dictionary
                    node_info = json.loads(match.metadata.get("text", "{}"))
                    
                    formatted_results.append({
                        "score": match.score,
                        "pdf_id": match.metadata.get("pdf_id"),
                        "chunk_index": match.metadata.get("chunk_index"),
                        "page_num": node_info.get("page_num", ""),
                        "image_path": node_info.get("image_path", ""),
                        "content": node_info.get("content", "")
                    })
                except (json.JSONDecodeError, KeyError) as e:
                    # Fallback with empty values for missing fields
                    formatted_results.append({
                        "score": match.score,
                        "pdf_id": match.metadata.get("pdf_id"),
                        "chunk_index": match.metadata.get("chunk_index"),
                        "page_num": "",
                        "image_path": "",
                        "content": match.metadata.get("text", "")
                    })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error in search_similar: {str(e)}")
            raise
        
    def generate_answer_from_chunks(self, query: str, chunks: List[Dict], max_tokens: int = 1000) -> str:
        """Generate an answer using the LLM based on retrieved chunks"""
        try:
            # Format the chunks into a single context
            context = "\n\n".join([
                f"Chunk {i+1}:\n{chunk['metadata']['text']}"
                for i, chunk in enumerate(chunks)
            ])
            
            # Create the prompt
            prompt = f"""Please provide a comprehensive answer to the following question using only the provided context. 
            If the answer cannot be fully derived from the context, please say so.

            Question: {query}

            Context:
            {context}

            Please provide a detailed answer and cite specific parts of the context where appropriate."""

            # Generate response using NVIDIA model
            response = self.embeddings_client.chat.completions.create(
                model="mistralai/mixtral-8x7b-instruct-v0.1",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error generating answer from chunks: {str(e)}")
            raise

    async def search_and_answer(self, query: str, top_k: int = 5) -> Dict:
        """Search for relevant chunks and generate an answer"""
        try:
            # First, search for relevant chunks
            search_results = self.search_similar(query, top_k)
            
            # Extract chunks from results
            chunks = [
                {
                    "score": match.score,
                    "metadata": match.metadata
                }
                for match in search_results.matches
            ]
            
            # Generate answer using chunks
            answer = self.generate_answer_from_chunks(query, chunks)
            
            return {
                "query": query,
                "answer": answer,
                "supporting_chunks": chunks,
                "total_chunks": len(chunks)
            }
            
        except Exception as e:
            logger.error(f"Error in search and answer: {str(e)}")
            raise

# Export the class
__all__ = ['TextProcessor']