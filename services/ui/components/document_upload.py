"""
Document Upload Component

Handles PDF document URL submission and processing status monitoring.
Provides interface for document validation and upload progress tracking.
"""

import streamlit as st
import requests
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime


class DocumentUpload:
    """Document upload and management component"""
    
    def __init__(self, config: Dict[str, Any], session_id: Optional[str] = None):
        """Initialize document upload component"""
        self.config = config
        self.session_id = session_id
        self.api_base_url = config['api_base_url']
        self.logger = logging.getLogger("ui.document_upload")
    
    def render(self):
        """Render the document upload interface"""
        if not self.session_id:
            st.warning("Please create a session to upload documents.")
            return
        
        # Document submission form
        self._render_upload_form()
        
        st.divider()
        
        # Document jobs monitoring
        self._render_job_monitoring()
        
        st.divider()
        
        # Upload guidelines
        with st.expander("📋 Upload Guidelines"):
            self._render_upload_guidelines()
    
    def _render_upload_form(self):
        """Render document URL submission form"""
        st.subheader("📤 Submit Document URL")
        
        with st.form("document_upload_form"):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                document_url = st.text_input(
                    "PDF Document URL",
                    placeholder="https://example.com/medical-protocol.pdf",
                    help="Enter a direct link to a PDF document (must end with .pdf)"
                )
            
            with col2:
                validate_content = st.checkbox(
                    "Validate Content",
                    value=True,
                    help="Check URL accessibility and file size before processing"
                )
            
            document_title = st.text_input(
                "Document Title (optional)",
                placeholder="Enter a descriptive title for this document",
                help="If not provided, title will be extracted from the URL"
            )
            
            col1, col2 = st.columns(2)
            with col1:
                submit_button = st.form_submit_button(
                    "Submit Document 📄",
                    type="primary",
                    use_container_width=True
                )
            
            with col2:
                validate_button = st.form_submit_button(
                    "Validate URL Only ✓",
                    type="secondary",
                    use_container_width=True
                )
        
        # Handle form submissions
        if submit_button and document_url.strip():
            self._submit_document(document_url.strip(), document_title.strip(), validate_content)
        
        if validate_button and document_url.strip():
            self._validate_document_url(document_url.strip())
    
    def _submit_document(self, url: str, title: str, validate_content: bool):
        """Submit document for processing"""
        try:
            payload = {
                "url": url,
                "title": title if title else None,
                "validate_content": validate_content,
                "metadata": {
                    "submitted_from": "streamlit_ui",
                    "user_agent": "RAG-101-UI/1.0"
                }
            }
            
            headers = {
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json"
            }
            
            with st.spinner("Submitting document for processing..."):
                response = requests.post(
                    f"{self.api_base_url}/documents/submit",
                    json=payload,
                    headers=headers,
                    timeout=30
                )
            
            if response.status_code == 202:
                job_data = response.json()
                
                # Add job to session state
                if 'document_jobs' not in st.session_state:
                    st.session_state.document_jobs = []
                
                st.session_state.document_jobs.append({
                    'job_id': job_data['job_id'],
                    'url': job_data['url'],
                    'title': job_data['title'],
                    'status': job_data['status'],
                    'submitted_at': job_data['submitted_at'],
                    'estimated_time': job_data.get('estimated_processing_time', 'Unknown')
                })
                
                st.success(f"✅ Document submitted successfully!")
                st.info(f"Job ID: {job_data['job_id']}")
                st.info(f"Estimated processing time: {job_data.get('estimated_processing_time', 'Unknown')}")
                
            elif response.status_code == 400:
                error_data = response.json()
                st.error(f"❌ Validation Error: {error_data.get('detail', 'Invalid request')}")
                
            elif response.status_code == 429:
                st.error("⏳ Rate limit exceeded. Please wait before submitting another document.")
                
            else:
                st.error(f"❌ Submission failed: {response.status_code} - {response.text}")
        
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Document submission failed: {e}")
            st.error(f"❌ Network error: {str(e)}")
        
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            st.error(f"❌ Unexpected error: {str(e)}")
    
    def _validate_document_url(self, url: str):
        """Validate document URL without submitting"""
        try:
            payload = {
                "url": url,
                "validate_content": True
            }
            
            with st.spinner("Validating document URL..."):
                response = requests.post(
                    f"{self.api_base_url}/documents/validate",
                    json=payload,
                    timeout=15
                )
            
            if response.status_code == 200:
                validation_data = response.json()
                
                if validation_data['valid']:
                    st.success("✅ URL is valid and accessible!")
                    
                    if validation_data.get('size_mb'):
                        st.info(f"📊 File size: {validation_data['size_mb']:.1f} MB")
                    
                    if validation_data.get('content_type'):
                        st.info(f"📄 Content type: {validation_data['content_type']}")
                        
                else:
                    st.error(f"❌ Validation failed: {validation_data.get('reason', 'Unknown error')}")
            
            else:
                st.error(f"❌ Validation request failed: {response.status_code}")
        
        except Exception as e:
            self.logger.error(f"URL validation failed: {e}")
            st.error(f"❌ Validation error: {str(e)}")
    
    def _render_job_monitoring(self):
        """Render document processing job monitoring"""
        st.subheader("📊 Document Processing Jobs")
        
        if not st.session_state.get('document_jobs'):
            st.info("No document processing jobs yet. Submit a document URL above to get started.")
            return
        
        # Refresh button
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🔄 Refresh Status", type="secondary"):
                self._refresh_job_statuses()
        
        # Jobs table
        for i, job in enumerate(st.session_state.document_jobs):
            with st.container():
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    st.markdown(f"**{job['title']}**")
                    st.caption(f"Job ID: {job['job_id'][:8]}...")
                    st.caption(f"URL: {job['url'][:50]}..." if len(job['url']) > 50 else job['url'])
                
                with col2:
                    status = job['status'].upper()
                    if status == 'COMPLETED':
                        st.success(f"✅ {status}")
                    elif status in ['PROCESSING', 'DOWNLOADING', 'EMBEDDING']:
                        st.info(f"⏳ {status}")
                    elif status == 'QUEUED':
                        st.warning(f"⏱️ {status}")
                    elif status in ['FAILED', 'ERROR']:
                        st.error(f"❌ {status}")
                    else:
                        st.text(f"📝 {status}")
                
                with col3:
                    st.caption(f"Submitted: {job['submitted_at'][:19]}")
                    st.caption(f"Est. time: {job['estimated_time']}")
                    
                    # Action buttons
                    if st.button(f"ℹ️ Details", key=f"details_{job['job_id']}", type="secondary"):
                        self._show_job_details(job['job_id'])
                
                st.divider()
    
    def _refresh_job_statuses(self):
        """Refresh status for all jobs"""
        if not st.session_state.get('document_jobs'):
            return
        
        for i, job in enumerate(st.session_state.document_jobs):
            try:
                response = requests.get(
                    f"{self.api_base_url}/documents/jobs/{job['job_id']}/status",
                    timeout=10
                )
                
                if response.status_code == 200:
                    status_data = response.json()
                    st.session_state.document_jobs[i]['status'] = status_data['status']
                    
            except Exception as e:
                self.logger.error(f"Failed to refresh job {job['job_id']}: {e}")
        
        st.rerun()
    
    def _show_job_details(self, job_id: str):
        """Show detailed job information"""
        try:
            response = requests.get(
                f"{self.api_base_url}/documents/jobs/{job_id}/status",
                timeout=10
            )
            
            if response.status_code == 200:
                job_details = response.json()
                
                with st.expander(f"Job Details: {job_id[:8]}...", expanded=True):
                    st.json(job_details)
            else:
                st.error(f"Failed to fetch job details: {response.status_code}")
                
        except Exception as e:
            st.error(f"Error fetching job details: {str(e)}")
    
    def _render_upload_guidelines(self):
        """Render document upload guidelines"""
        st.markdown("""
        ### Document Requirements:
        - **Format**: PDF files only (.pdf extension)
        - **Size**: Maximum 50 MB per document
        - **Accessibility**: URL must be publicly accessible
        - **Content**: Medical protocols, clinical guidelines, or research documents
        
        ### Supported URL Types:
        - Direct PDF links (ending with .pdf)
        - Government health ministry documents
        - Medical journal articles
        - Clinical protocol documents (PCDT)
        
        ### Processing Pipeline:
        1. **URL Validation**: Check accessibility and file format
        2. **Download**: Retrieve PDF document
        3. **Text Extraction**: Extract text content from PDF
        4. **Chunking**: Split content into searchable segments
        5. **Embedding**: Generate vector embeddings for semantic search
        6. **Indexing**: Store in vector database for Q&A retrieval
        
        ### Tips for Best Results:
        - Use official sources from health ministries or medical institutions
        - Ensure documents are in Portuguese for Brazilian medical protocols
        - Provide descriptive titles to help with document organization
        - Validate URLs before submission to catch issues early
        
        ### Processing Status:
        - **Queued**: Waiting for processing
        - **Downloading**: Fetching PDF from URL
        - **Processing**: Extracting text and analyzing content
        - **Embedding**: Generating semantic vectors
        - **Completed**: Ready for Q&A queries
        - **Failed**: Processing encountered an error
        """)


def get_job_status_color(status: str) -> str:
    """Get color for job status display"""
    status = status.lower()
    if status == 'completed':
        return 'green'
    elif status in ['processing', 'downloading', 'embedding']:
        return 'blue'
    elif status == 'queued':
        return 'orange'
    elif status in ['failed', 'error']:
        return 'red'
    else:
        return 'gray'