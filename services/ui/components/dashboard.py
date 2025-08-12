"""
Dashboard Component - Block-based Workflow Design

Real-time monitoring dashboard with connected workflow blocks showing:
- Milvus document count
- Document processing workflow blocks (download → chunks → embeddings → complete)
- Q&A workflow blocks (questions → answers)
- Interactive forms below workflows
- Top-right refresh controls
"""

import streamlit as st
import requests
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("ui.dashboard")


class Dashboard:
    """Block-based workflow dashboard component"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize dashboard component"""
        self.config = config
        self.api_base_url = config['api_base_url']
        self.logger = logging.getLogger("ui.dashboard")
        
        # Initialize dashboard state
        if 'dashboard_auto_refresh' not in st.session_state:
            st.session_state.dashboard_auto_refresh = True
        if 'dashboard_refresh_interval' not in st.session_state:
            st.session_state.dashboard_refresh_interval = 5
        if 'last_streams_data' not in st.session_state:
            st.session_state.last_streams_data = None
        
        # Add custom CSS for workflow blocks
        self._inject_custom_css()
    
    def _inject_custom_css(self):
        """Inject custom CSS for workflow block styling"""
        st.markdown("""
        <style>
        .workflow-block {
            background: white;
            border: 2px solid #ddd;
            border-radius: 10px;
            padding: 15px;
            text-align: center;
            margin: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            min-height: 80px;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        
        .workflow-block-download {
            border-color: #1f77b4;
            background-color: #e8f4f8;
        }
        
        .workflow-block-chunks {
            border-color: #ff7f0e;
            background-color: #fff2e8;
        }
        
        .workflow-block-embeddings {
            border-color: #2ca02c;
            background-color: #e8f5e8;
        }
        
        .workflow-block-complete {
            border-color: #d62728;
            background-color: #f8e8e8;
        }
        
        .workflow-block-questions {
            border-color: #3498db;
            background-color: #e8f2ff;
        }
        
        .workflow-block-answers {
            border-color: #2ecc71;
            background-color: #e8f8f2;
        }
        
        .workflow-arrow {
            font-size: 24px;
            color: #666;
            text-align: center;
            padding: 20px 0;
        }
        
        .block-title {
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 5px;
            color: black;
        }
        
        .block-count {
            font-size: 20px;
            font-weight: bold;
            color: #333;
        }
        
        .refresh-container {
            text-align: right;
            margin-bottom: 20px;
        }
        </style>
        """, unsafe_allow_html=True)
    
    def render(self):
        """Render the block-based dashboard interface"""
        # Header with title and top-right refresh controls
        self._render_header_with_refresh()
        
        st.divider()
        
        # Fetch current data from streams endpoint
        streams_data = self._fetch_streams_data()
        
        if streams_data:
            # Document processing workflow blocks
            self._render_document_workflow_blocks(streams_data)
            
            st.divider()
            
            # Add Document form between workflows
            self._render_add_document_form()
            
            st.divider()
            
            # Q&A workflow blocks
            self._render_qa_workflow_blocks(streams_data)
            
            st.divider()
            
            # Question form at bottom
            self._render_question_form()
            
        else:
            st.error("⚠️ Unable to fetch dashboard data. Please check if the API service is running.")
            
        # Handle auto-refresh
        self._handle_auto_refresh()
    
    def _render_header_with_refresh(self):
        """Render compact header with title on left and refresh controls on right"""
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("📊 RAG System Dashboard")
            # Add document count inline with title
            streams_data = st.session_state.get('last_streams_data')
            if streams_data:
                doc_count = streams_data.get('milvus_documents', 0)
                st.markdown(f'<p style="font-size: 1.2rem; margin: 0; color: white;">Documents Milvus: {doc_count:,}</p>', unsafe_allow_html=True)
        
        with col2:
            # Refresh controls in a compact layout
            refresh_col1, refresh_col2, refresh_col3 = st.columns([2, 2, 1])
            
            with refresh_col1:
                st.session_state.dashboard_auto_refresh = st.checkbox(
                    "Auto-refresh", 
                    value=st.session_state.dashboard_auto_refresh,
                    key="dashboard_auto_refresh_checkbox"
                )
            
            with refresh_col2:
                refresh_options = {
                    "1s": 1,
                    "5s": 5, 
                    "10s": 10,
                    "30s": 30,
                    "1m": 60
                }
                
                selected_interval = st.selectbox(
                    "Refresh",
                    options=list(refresh_options.keys()),
                    index=1,  # Default to 5s
                    disabled=not st.session_state.dashboard_auto_refresh,
                    label_visibility="collapsed",
                    key="dashboard_refresh_interval_select"
                )
                
                st.session_state.dashboard_refresh_interval = refresh_options[selected_interval]
            
            with refresh_col3:
                if st.button("🔄", help="Refresh Now", key="dashboard_refresh_button"):
                    st.session_state.last_streams_data = None  # Force refresh
                    st.rerun()
            
            # Show last updated time below refresh controls, right-aligned
            if st.session_state.last_streams_data:
                last_updated = st.session_state.last_streams_data.get('timestamp', 'Unknown')
                if last_updated != 'Unknown':
                    try:
                        dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                        time_str = dt.strftime('%H:%M:%S')
                        st.markdown(f'<p style="text-align: right; font-size: 0.8rem; color: #666; margin: 0;">Last updated: {time_str}</p>', unsafe_allow_html=True)
                    except:
                        st.markdown('<p style="text-align: right; font-size: 0.8rem; color: #666; margin: 0;">Last updated: Recent</p>', unsafe_allow_html=True)
    
    def _fetch_streams_data(self) -> Optional[Dict[str, Any]]:
        """Fetch data from streams API endpoint"""
        try:
            response = requests.get(
                f"{self.api_base_url}/api/v1/streams/",
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                st.session_state.last_streams_data = data
                return data
            else:
                self.logger.error(f"Streams API returned {response.status_code}")
                return st.session_state.last_streams_data  # Return cached data
                
        except Exception as e:
            self.logger.error(f"Failed to fetch streams data: {e}")
            return st.session_state.last_streams_data  # Return cached data
    
    def _render_document_count(self, streams_data: Dict[str, Any]):
        """Render document count metric"""
        doc_count = streams_data.get('milvus_documents', 0)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.metric(
                label="📚 Documents in Milvus",
                value=f"{doc_count:,}",
                help="Total number of document chunks in vector database"
            )
    
    def _render_document_workflow_blocks(self, streams_data: Dict[str, Any]):
        """Render document processing workflow as connected blocks"""
        st.subheader("Document Processing Workflow")
        
        workflow = streams_data.get('document_workflow', {})
        
        # Create 7 columns: block, arrow, block, arrow, block, arrow, block
        col1, col2, col3, col4, col5, col6, col7 = st.columns([2, 1, 2, 1, 2, 1, 2])
        
        with col1:
            self._render_workflow_block(
                title="Download",
                count=workflow.get('downloads', 0),
                block_type="download",
                help_text="PDFs downloaded from URLs"
            )
        
        with col2:
            st.markdown('<div class="workflow-arrow">───▶</div>', unsafe_allow_html=True)
        
        with col3:
            self._render_workflow_block(
                title="Chunks",
                count=workflow.get('chunks', 0),
                block_type="chunks",
                help_text="Text chunks created"
            )
        
        with col4:
            st.markdown('<div class="workflow-arrow">───▶</div>', unsafe_allow_html=True)
        
        with col5:
            self._render_workflow_block(
                title="Embeddings",
                count=workflow.get('embeddings', 0),
                block_type="embeddings",
                help_text="Vector embeddings generated"
            )
        
        with col6:
            st.markdown('<div class="workflow-arrow">───▶</div>', unsafe_allow_html=True)
        
        with col7:
            self._render_workflow_block(
                title="Complete",
                count=workflow.get('complete', 0),
                block_type="complete",
                help_text="Fully processed documents"
            )
    
    def _render_qa_workflow_blocks(self, streams_data: Dict[str, Any]):
        """Render Q&A workflow as connected blocks"""
        st.subheader("Q&A Workflow")
        
        qa_workflow = streams_data.get('qa_workflow', {})
        
        # Create 3 columns: questions block, arrow, answers block
        col1, col2, col3, col4, col5 = st.columns([2, 1, 2, 1, 2])
        
        with col1:
            # Empty column for centering
            pass
        
        with col2:
            self._render_workflow_block(
                title="❓ Questions",
                count=qa_workflow.get('questions', 0),
                block_type="questions",
                help_text="Questions submitted by users"
            )
        
        with col3:
            st.markdown('<div class="workflow-arrow">───▶</div>', unsafe_allow_html=True)
        
        with col4:
            self._render_workflow_block(
                title="💬 Answers",
                count=qa_workflow.get('answers_total', 0),
                block_type="answers",
                help_text="Answers generated by AI"
            )
        
        with col5:
            # Empty column for centering
            pass
    
    def _render_workflow_block(self, title: str, count: int, block_type: str, help_text: str):
        """Render individual workflow block"""
        block_html = f"""
        <div class="workflow-block workflow-block-{block_type}" title="{help_text}">
            <div class="block-title">{title}</div>
            <div class="block-count">{count} msgs</div>
        </div>
        """
        st.markdown(block_html, unsafe_allow_html=True)
    
    def _render_add_document_form(self):
        """Render document upload form between workflows"""
        st.subheader("📄 Add Document")
        
        with st.form("dashboard_document_form_unique", clear_on_submit=True):
            doc_url = st.text_input(
                "Document URL",
                placeholder="https://example.com/document.pdf",
                help="Enter a PDF URL to process and add to the knowledge base"
            )
            
            submit_doc = st.form_submit_button("🔄 Process Document", type="primary")
            
            if submit_doc and doc_url:
                self._submit_document(doc_url)
    
    def _render_question_form(self):
        """Render question form at bottom"""
        st.subheader("❓ Ask Question")
        
        with st.form("dashboard_question_form_unique", clear_on_submit=True):
            question = st.text_area(
                "Your Question",
                placeholder="Ask a question about the medical documents...",
                height=100,
                help="Submit a question to get an AI-generated answer"
            )
            
            submit_question = st.form_submit_button("💬 Get Answer", type="primary")
            
            if submit_question and question:
                self._submit_question(question)
    
    def _submit_document(self, url: str):
        """Submit document URL for processing"""
        try:
            response = requests.post(
                f"{self.api_base_url}/api/v1/document-download",
                json=[url],
                timeout=10
            )
            
            if response.status_code == 200:
                st.success(f"✅ Document submitted for processing: {url}")
                st.info("📊 Check the workflow blocks above to monitor processing progress.")
            else:
                st.error(f"❌ Failed to submit document: HTTP {response.status_code}")
                
        except Exception as e:
            st.error(f"❌ Error submitting document: {str(e)}")
    
    def _submit_question(self, question: str):
        """Submit question and display answer"""
        if not hasattr(st.session_state, 'session_id') or not st.session_state.session_id:
            st.error("❌ Please start a session first (use the sidebar)")
            return
            
        try:
            # Submit question
            response = requests.post(
                f"{self.api_base_url}/api/v1/questions/",
                json={
                    "question": question,
                    "session_id": st.session_state.session_id
                },
                timeout=10
            )
            
            if response.status_code == 200:
                st.success("✅ Question submitted successfully!")
                st.info("💬 Answer will be delivered via WebSocket. Check Q&A workflow blocks above.")
                
                # Show the question for reference
                with st.expander("📝 Your Question", expanded=True):
                    st.write(question)
                    
            else:
                st.error(f"❌ Failed to submit question: HTTP {response.status_code}")
                
        except Exception as e:
            st.error(f"❌ Error submitting question: {str(e)}")
    
    def _handle_auto_refresh(self):
        """Handle auto-refresh functionality"""
        if st.session_state.dashboard_auto_refresh:
            from streamlit_autorefresh import st_autorefresh
            
            # Auto-refresh every N seconds (only if auto-refresh is enabled)
            st_autorefresh(
                interval=st.session_state.dashboard_refresh_interval * 1000,
                key="dashboard_autorefresh"
            )