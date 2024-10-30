import streamlit as st
import requests
import base64
from datetime import datetime
import os
from PIL import Image
from io import BytesIO
import urllib.parse
import json
import logging
import re
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FASTAPI_URL = os.getenv("FASTAPI_URL", "http://fastapi-app:8000")

def init_session_state():
    if 'selected_pdf' not in st.session_state:
        st.session_state.selected_pdf = None
    if 'current_report' not in st.session_state:
        st.session_state.current_report = None
    if 'saved_notes' not in st.session_state:
        st.session_state.saved_notes = []
    if 'extracted_status' not in st.session_state:
        st.session_state.extracted_status = {}

def load_css():
    st.markdown("""
        <style>
            .doc-selector { 
                background-color: #ffffff; 
                padding: 1.5rem; 
                border-radius: 8px; 
                margin: 1rem auto; 
                max-width: 800px; 
                border: 1px solid #e9ecef; 
            }
            .pdf-container { 
                width: 100%; 
                max-width: 800px; 
                margin: 1rem auto; 
                background: white; 
                padding: 20px; 
                border-radius: 8px; 
                box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
            }
            .pdf-viewer { 
                width: 100%; 
                height: 800px; 
                border: none; 
                border-radius: 4px; 
            }
            .qa-container { 
                background-color: #f8f9fa; 
                padding: 1.5rem; 
                border-radius: 8px; 
                margin: 1rem auto; 
                max-width: 800px; 
            }
            .report-container { 
                background-color: #ffffff; 
                padding: 2rem; 
                border-radius: 8px; 
                margin: 1rem 0; 
                border: 1px solid #e9ecef;
                line-height: 1.6;
            }
            .block-container { 
                margin: 1rem 0; 
                padding: 1rem; 
                border-radius: 4px; 
                background-color: #f8f9fa; 
                white-space: pre-wrap; 
                word-wrap: break-word;
                line-height: 1.8;
            }
  '.image-block img { max-width: 100%; height: auto; }',
    '.image-block .caption { font-size: 0.9rem; color: #6c757d; text-align: center; }',
    '.metadata-container { font-size: 0.85rem; color: #6c757d; border-top: 1px solid #dee2e6; padding-top: 0.5rem; }',
            }
            .metadata-container { 
                font-size: 0.9rem; 
                color: #6c757d; 
                margin-top: 1rem; 
                padding: 0.5rem; 
                text-align: right;
                border-top: 1px solid #e9ecef;
            }
            iframe { 
                border: none !important; 
                width: 100% !important; 
                height: 800px !important; 
            }
        </style>
    """, unsafe_allow_html=True)

def display_pdf_viewer(pdf_name: str):
    try:
        response = requests.get(f"{FASTAPI_URL}/pdfs/{pdf_name}/document")
        response.raise_for_status()
        base64_pdf = base64.b64encode(response.content).decode('utf-8')
        
        st.markdown('<div class="pdf-container">', unsafe_allow_html=True)
        pdf_display = f'<iframe class="pdf-viewer" src="data:application/pdf;base64,{base64_pdf}#toolbar=1&navpanes=1&scrollbar=1"></iframe>'
        st.markdown(pdf_display, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.download_button("Download PDF", response.content, f"{pdf_name}.pdf", "application/pdf", use_container_width=True)
    except requests.RequestException as e:
        st.error(f"Error loading PDF: {str(e)}")

def test_extract_pdf(folder_name: str) -> bool:
    try:
        logger.info(f"Starting extraction for {folder_name}")
        encoded_folder_name = urllib.parse.quote(folder_name)
        
        with st.status("Processing document...", expanded=True) as status:
            st.write("Extracting document content...")
            
            response = requests.post(
                f"{FASTAPI_URL}/pdfs/{encoded_folder_name}/test-extract"
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success":
                    logger.info(f"Extraction successful for {folder_name}")
                    st.session_state.extracted_status[folder_name] = True
                    status.update(label="Document processed successfully!", state="complete")
                    return True
                else:
                    error_msg = f"Extraction failed: {result.get('detail', 'Unknown error')}"
                    logger.error(error_msg)
                    status.update(label="Processing failed!", state="error")
                    st.error(error_msg)
            else:
                error_msg = f"Extraction failed with status code: {response.status_code}"
                logger.error(error_msg)
                status.update(label="Processing failed!", state="error")
                st.error(error_msg)
            return False
    except Exception as e:
        error_msg = f"Error during extraction: {str(e)}"
        logger.error(error_msg)
        st.error(error_msg)
        return False

def process_query(query: str, folder_name: str, top_k: int = 5):
    try:
        encoded_folder_name = urllib.parse.quote(folder_name)
        logger.info(f"Processing query for {folder_name}")
        
        with st.status("Analyzing document...", expanded=True) as status:
            response = requests.post(
                f"{FASTAPI_URL}/pdfs/{encoded_folder_name}/search-and-process",
                json={
                    "query": query,
                    "top_k": top_k,
                    "pdf_id": folder_name
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                status.update(label="Analysis complete!", state="complete")
                return result
            else:
                error_msg = f"Error processing query: {response.text}"
                logger.error(error_msg)
                status.update(label="Analysis failed!", state="error")
                st.error(error_msg)
                return None
                
    except Exception as e:
        error_msg = f"Error processing query: {str(e)}"
        logger.error(error_msg)
        st.error(error_msg)
        return None


def clean_text_content(text: str) -> str:
    """Clean and format text content from the report."""
    try:
        # Remove code block markers
        text = re.sub(r'```[a-zA-Z]*\n|```', '', text)
        
        # Remove specific markers
        text = re.sub(r'\*\*vbnet|\*\*Report:|\*\*Text Analysis:', '', text)
        
        # Remove block markers
        text = re.sub(r'\[TEXT\]|\[/TEXT\]|\[IMAGE\]|\[/IMAGE\]', '', text)
        
        # Remove chunk references
        text = re.sub(r'\(Chunk \d+\)', '', text)
        text = re.sub(r'\(Figure \d+\)', '', text)
        
        # Clean up multiple newlines
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        # Clean up any remaining markdown artifacts
        text = re.sub(r'\*\*\s*', '**', text)  # Fix spacing in bold text
        text = re.sub(r'\_\_\s*', '__', text)  # Fix spacing in underlined text
        
        # Remove any leading/trailing whitespace
        text = text.strip()
        
        return text
    except Exception as e:
        logger.error(f"Error cleaning text content: {str(e)}")
        return text  # Return original text if cleaning fails

def render_report_blocks(report_data):
    """Render report blocks with text and images."""
    st.markdown("<div class='report-container'>", unsafe_allow_html=True)
    
    try:
        for block in report_data["report"]["blocks"]:
            if "text" in block:
                # Clean and render text block
                try:
                    cleaned_text = clean_text_content(block["text"])
                    st.markdown(
                        f"<div class='block-container'>{cleaned_text}</div>", 
                        unsafe_allow_html=True
                    )
                except Exception as text_error:
                    logger.error(f"Error rendering text block: {str(text_error)}")
                    st.error("Error rendering text content")
                
            elif "file_path" in block:
                # Render image block
                st.markdown("<div class='image-block'>", unsafe_allow_html=True)
                try:
                    # Construct the full URL for the image
                    image_url = f"{FASTAPI_URL}{block['file_path']}"
                    logger.info(f"Accessing image URL: {image_url}")
                    
                    # Make the request with error handling
                    response = requests.get(image_url)
                    if response.status_code == 200:
                        try:
                            image = Image.open(BytesIO(response.content))
                            st.image(
                                image,
                                use_column_width=True,
                                caption=f"Image from document"
                            )
                        except Exception as img_error:
                            logger.error(f"Error processing image: {str(img_error)}")
                            st.error(f"Error processing image: {str(img_error)}")
                    else:
                        logger.error(f"Failed to load image. Status code: {response.status_code}")
                        logger.error(f"Response content: {response.text[:200]}")
                        st.error(f"Could not load image (Status code: {response.status_code})")
                        
                except Exception as e:
                    logger.error(f"Error in image block rendering: {str(e)}")
                    st.error(f"Error displaying image: {str(e)}")
                
                st.markdown("</div>", unsafe_allow_html=True)

        # Add metadata
        st.markdown("<div class='metadata-container'>", unsafe_allow_html=True)
        timestamp = datetime.fromisoformat(report_data['metadata']['processing_timestamp'])
        st.markdown(
            f"Generated: {timestamp.strftime('%Y-%m-%d %H:%M:%S')} | "
            f"Chunks analyzed: {report_data['metadata']['chunks_analyzed']} | "
            f"Model: {report_data['metadata']['model_used']}", 
            unsafe_allow_html=True
        )
        st.markdown("</div>", unsafe_allow_html=True)
        
    except Exception as e:
        logger.error(f"Error rendering report blocks: {str(e)}")
        st.error("Error rendering report content")


def ask_question(query: str, folder_name: str, top_k: int = 5):
    try:
        # Check if we need to extract content
        if not st.session_state.extracted_status.get(folder_name, False):
            if not test_extract_pdf(folder_name):
                return None
        
        # Process the query
        return process_query(query, folder_name, top_k)
        
    except Exception as e:
        logger.error(f"Error in ask_question: {str(e)}")
        st.error(f"Error processing request: {str(e)}")
        return None

def save_as_notes(report_data: Dict):
    # Extract clean text without technical details
    text_blocks = []
    for block in report_data["report"]["blocks"]:
        if "text" in block:
            text_content = block["text"]
            if "Report:" in text_content and "Tool Call:" in text_content:
                text_content = text_content.split("Report:")[1].split("Tool Call:")[0]
            text_content = text_content.replace("---", "").strip()
            text_content = re.sub(r'\(Chunk \d+\)', '', text_content)
            text_content = re.sub(r'\(Figure \d+\)', '', text_content)
            text_blocks.append(text_content)

    note = {
        "timestamp": datetime.now().isoformat(),
        "query": report_data["metadata"]["query"],
        "document": report_data["metadata"]["folder_name"],
        "text_blocks": text_blocks,
        "image_paths": [block["file_path"] for block in report_data["report"]["blocks"] if "file_path" in block]
    }
    st.session_state.saved_notes.append(note)
    return len(st.session_state.saved_notes)

def fetch_pdfs():
    try:
        response = requests.get(f"{FASTAPI_URL}/pdfs/all")
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"Failed to load PDF list: {str(e)}")
        return []

def show():
    init_session_state()
    load_css()
    
    st.title("Document Q&A Interface")
    
    st.markdown("<div class='doc-selector'>", unsafe_allow_html=True)
    pdfs = fetch_pdfs()
    if not pdfs:
        st.warning("No documents available")
        return
    
    selected_pdf = st.selectbox(
        "Select a document",
        options=[""] + [pdf['title'] for pdf in pdfs],
        index=0,
        key="pdf_selector"
    )
    st.markdown("</div>", unsafe_allow_html=True)
    
    if selected_pdf:
        st.session_state.selected_pdf = selected_pdf
        display_pdf_viewer(selected_pdf)
        
        st.markdown("<div class='qa-container'>", unsafe_allow_html=True)
        col1, col2 = st.columns([4, 1])
        
        with col1:
            question = st.text_area(
                "Ask a question about this document:",
                height=100,
                placeholder="Enter your question here..."
            )
        
        with col2:
            top_k = st.number_input(
                "Results",
                min_value=1,
                max_value=10,
                value=5
            )
            
            if st.button("Generate Report", use_container_width=True):
                if question:
                    result = ask_question(question, selected_pdf, top_k)
                    if result and result.get("status") == "success":
                        st.session_state.current_report = result
        
        if st.session_state.current_report:
            render_report_blocks(st.session_state.current_report)
            
            if st.button("Save as Notes", use_container_width=True):
                note_number = save_as_notes(st.session_state.current_report)
                st.success(f"Saved as Note #{note_number}")
        
        st.markdown("</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    show()
