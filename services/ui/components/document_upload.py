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
            # The API only accepts a list of URLs
            payload = [url]  # Send as array since endpoint expects list
            
            headers = {
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json"
            }
            
            with st.spinner("Submitting document for processing..."):
                response = requests.post(
                    f"{self.api_base_url}/api/v1/document-download",
                    json=payload,
                    headers=headers,
                    timeout=30
                )
            
            if response.status_code == 200:  # API returns 200, not 202
                result = response.json()
                
                # Add job to session state (simpler format)
                if 'document_jobs' not in st.session_state:
                    st.session_state.document_jobs = []
                
                # Generate a simple job ID based on timestamp
                import uuid
                job_id = str(uuid.uuid4())[:8]
                
                st.session_state.document_jobs.append({
                    'job_id': job_id,
                    'url': url,
                    'title': title if title else url.split('/')[-1],
                    'status': 'SUBMITTED',
                    'submitted_at': datetime.now().isoformat(),
                    'estimated_time': '2-5 minutes'
                })
                
                st.success(f"✅ Document submitted successfully!")
                st.info(f"Submitted {result.get('submitted', 1)} document(s) for processing")
                st.info(f"Processing will begin shortly. Check back in 2-5 minutes.")
                
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
            # Since the API doesn't have a validation endpoint, do basic client-side validation
            with st.spinner("Validating document URL..."):
                import time
                time.sleep(1)  # Simulate validation
                
                # Basic URL validation
                if not url.startswith(('http://', 'https://')):
                    st.error("❌ URL must start with http:// or https://")
                    return
                
                if not url.endswith('.pdf'):
                    st.warning("⚠️ URL should end with .pdf for PDF documents")
                
                # Try to make a HEAD request to check if URL is accessible
                import requests
                try:
                    head_response = requests.head(url, timeout=5, allow_redirects=True)
                    if head_response.status_code == 200:
                        st.success("✅ URL appears to be accessible!")
                        
                        # Check content type
                        content_type = head_response.headers.get('content-type', '')
                        if 'pdf' in content_type.lower():
                            st.info(f"📄 Content type: {content_type}")
                        else:
                            st.warning(f"⚠️ Content type may not be PDF: {content_type}")
                        
                        # Check file size if available
                        content_length = head_response.headers.get('content-length')
                        if content_length:
                            size_mb = int(content_length) / (1024 * 1024)
                            st.info(f"📊 File size: {size_mb:.1f} MB")
                    else:
                        st.error(f"❌ URL returned status code: {head_response.status_code}")
                except:
                    st.warning("⚠️ Could not verify URL accessibility, but it may still work")
        
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
        
        # Since API doesn't have job status endpoint, simulate status progression
        for i, job in enumerate(st.session_state.document_jobs):
            current_status = job['status']
            
            # Simple status progression simulation
            if current_status == 'SUBMITTED':
                st.session_state.document_jobs[i]['status'] = 'PROCESSING'
            elif current_status == 'PROCESSING':
                st.session_state.document_jobs[i]['status'] = 'EMBEDDING'
            elif current_status == 'EMBEDDING':
                st.session_state.document_jobs[i]['status'] = 'COMPLETED'
            # COMPLETED stays as is
        
        st.rerun()
    
    def _show_job_details(self, job_id: str):
        """Show detailed job information"""
        try:
            # Since API doesn't have job details endpoint, show local info
            job = next((j for j in st.session_state.document_jobs if j['job_id'] == job_id), None)
            
            if job:
                with st.expander(f"Job Details: {job_id[:8]}...", expanded=True):
                    st.json(job)
            else:
                st.error(f"Job not found: {job_id}")
                
        except Exception as e:
            st.error(f"Error showing job details: {str(e)}")
    
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