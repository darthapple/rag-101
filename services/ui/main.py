"""
RAG-101 Streamlit UI Application

Main application entry point for the medical document Q&A system.
Provides an interactive web interface for document upload, question submission,
and real-time answer streaming with system monitoring dashboard.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx
from streamlit_autorefresh import st_autorefresh

# Add project root to Python path  
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ui.main")


def load_config() -> Dict[str, Any]:
    """Load configuration from environment variables"""
    return {
        'api_base_url': os.getenv('API_BASE_URL', 'http://localhost:8000'),
        'ws_base_url': os.getenv('WS_BASE_URL', 'ws://localhost:8000'),
        'nats_url': os.getenv('NATS_URL', 'nats://localhost:4222'),
        'session_ttl': int(os.getenv('SESSION_TTL', '3600')),
        'debug': os.getenv('DEBUG', 'false').lower() == 'true',
        'auto_refresh_interval': int(os.getenv('AUTO_REFRESH_INTERVAL', '30'))
    }


def configure_page():
    """Configure Streamlit page settings"""
    st.set_page_config(
        page_title="RAG-101 Medical Q&A",
        page_icon="🏥",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            'Get Help': 'https://github.com/rag-101/docs',
            'Report a bug': 'https://github.com/rag-101/issues',
            'About': "RAG-101 - Medical Document Q&A System"
        }
    )
    
    # Custom CSS
    st.markdown("""
    <style>
    .main-header {
        text-align: center;
        padding: 2rem 0;
        background: linear-gradient(90deg, #1f77b4, #17becf);
        color: white;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    
    .status-indicator {
        display: inline-block;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        margin-right: 8px;
    }
    
    .status-healthy { background-color: #28a745; }
    .status-warning { background-color: #ffc107; }
    .status-error { background-color: #dc3545; }
    
    .metric-card {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border-left: 4px solid #1f77b4;
    }
    
    .sidebar .stSelectbox > div > div > select {
        background-color: #f0f2f6;
    }
    
    .chat-message {
        padding: 1rem;
        border-radius: 8px;
        margin: 0.5rem 0;
        border-left: 4px solid #1f77b4;
        background: #f8f9fa;
    }
    
    .user-message {
        border-left-color: #28a745;
        background: #e8f5e9;
    }
    
    .assistant-message {
        border-left-color: #1f77b4;
        background: #e3f2fd;
    }
    </style>
    """, unsafe_allow_html=True)


def initialize_session_state():
    """Initialize Streamlit session state variables"""
    if 'config' not in st.session_state:
        st.session_state.config = load_config()
    
    if 'session_id' not in st.session_state:
        st.session_state.session_id = None
    
    if 'session_nickname' not in st.session_state:
        st.session_state.session_nickname = None
    
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    
    if 'document_jobs' not in st.session_state:
        st.session_state.document_jobs = []
    
    if 'system_status' not in st.session_state:
        st.session_state.system_status = {
            'api': 'unknown',
            'websocket': 'unknown',
            'last_check': None
        }
    
    if 'page' not in st.session_state:
        st.session_state.page = 'Chat'


def render_header():
    """Render application header"""
    st.markdown("""
    <div class="main-header">
        <h1>🏥 RAG-101 Medical Q&A System</h1>
        <p>Intelligent document analysis for Brazilian clinical protocols (PCDT)</p>
    </div>
    """, unsafe_allow_html=True)


def render_sidebar():
    """Render application sidebar"""
    with st.sidebar:
        st.header("🔧 System Controls")
        
        # Page selection
        st.session_state.page = st.selectbox(
            "Select Page",
            ["Chat", "Document Upload", "Dashboard", "Settings"],
            index=0
        )
        
        st.divider()
        
        # Session management
        st.subheader("👤 Session")
        
        if st.session_state.session_id:
            st.success(f"Connected: {st.session_state.session_nickname}")
            st.caption(f"ID: {st.session_state.session_id[:8]}...")
            
            if st.button("End Session", type="secondary"):
                # Clear session data
                st.session_state.session_id = None
                st.session_state.session_nickname = None
                st.session_state.chat_history = []
                st.rerun()
        else:
            with st.form("session_form"):
                nickname = st.text_input(
                    "Nickname (optional)",
                    placeholder="Enter your name..."
                )
                
                if st.form_submit_button("Start Session", type="primary"):
                    try:
                        # Import here to avoid circular imports
                        from components.session_manager import SessionManager
                        
                        session_manager = SessionManager(st.session_state.config)
                        session_data = session_manager.create_session(nickname)
                        
                        if session_data:
                            st.session_state.session_id = session_data['session_id']
                            st.session_state.session_nickname = session_data['nickname']
                            st.success("Session created successfully!")
                            st.rerun()
                        else:
                            st.error("Failed to create session")
                    except Exception as e:
                        st.error(f"Session creation failed: {str(e)}")
        
        st.divider()
        
        # System status
        st.subheader("📊 System Status")
        
        # Auto-refresh toggle
        auto_refresh = st.checkbox("Auto-refresh", value=True)
        
        if auto_refresh:
            # Auto-refresh every 30 seconds
            st_autorefresh(interval=st.session_state.config['auto_refresh_interval'] * 1000, key="status_refresh")
        
        # Update WebSocket status before displaying
        try:
            from components.websocket_client import update_websocket_status
            update_websocket_status()
        except ImportError:
            pass  # WebSocket client may not be available
        
        # Render status indicators (API and WebSocket only)
        # API Status
        api_status = st.session_state.system_status.get('api', 'unknown')
        if api_status == 'healthy':
            st.markdown('🟢 **API:** Conectada')
        elif api_status == 'error':
            st.markdown('🔴 **API:** Erro')
        else:
            st.markdown('🟡 **API:** Desconhecida')
        
        # WebSocket Status with animated progress
        if st.session_state.get('websocket_connected', False):
            st.markdown('🟢 **WebSocket:** Ativo')
        elif st.session_state.get('websocket_connecting', False):
            # Show progress bar while connecting
            st.markdown('🔄 **WebSocket:** Conectando...')
            progress_placeholder = st.empty()
            with progress_placeholder:
                st.progress(0.5, text="Estabelecendo conexão...")
        else:
            st.markdown('🟡 **WebSocket:** Inativo')
        
        # Manual refresh button
        if st.button("Refresh Status", type="secondary"):
            # Trigger status check
            check_system_status()
            st.rerun()
        
        # Last check timestamp
        if st.session_state.system_status['last_check']:
            st.caption(f"Last check: {st.session_state.system_status['last_check']}")


def check_system_status():
    """Check system component status"""
    import requests
    from datetime import datetime
    
    try:
        # Check API service
        api_url = f"{st.session_state.config['api_base_url']}/health"
        response = requests.get(api_url, timeout=5)
        
        if response.status_code == 200:
            st.session_state.system_status['api'] = 'healthy'
        else:
            st.session_state.system_status['api'] = 'error'
    except Exception:
        st.session_state.system_status['api'] = 'error'
    
    # Update WebSocket status from client
    try:
        from components.websocket_client import update_websocket_status
        update_websocket_status()
    except ImportError:
        pass  # WebSocket client may not be available
    
    # Update last check time
    st.session_state.system_status['last_check'] = datetime.now().strftime("%H:%M:%S")


def render_main_content():
    """Render main content based on selected page"""
    page = st.session_state.page
    
    if page == "Chat":
        render_chat_page()
    elif page == "Document Upload":
        render_document_page()
    elif page == "Dashboard":
        render_dashboard_page()
    elif page == "Settings":
        render_settings_page()


def render_chat_page():
    """Render chat interface page"""
    st.header("💬 Medical Q&A Chat")
    
    if not st.session_state.session_id:
        st.info("Please start a session from the sidebar to begin chatting.")
        return
    
    try:
        from components.chat_interface import ChatInterface
        from components.websocket_client import process_websocket_messages, initialize_websocket_integration, update_websocket_status
        
        # Initialize WebSocket integration
        initialize_websocket_integration()
        
        # Auto-refresh while WebSocket is connecting (first 10 seconds after session creation)
        if st.session_state.get('websocket_connecting', False) and not st.session_state.get('websocket_connected', False):
            if 'websocket_check_time' in st.session_state:
                st.session_state.websocket_check_time = st.session_state.get('websocket_check_time', 0) + 1
                if st.session_state.websocket_check_time < 10:  # Check for 10 seconds
                    # Update status and refresh every 2 seconds
                    update_websocket_status()
                    import time
                    time.sleep(2)
                    st.rerun()
        
        # Create chat interface
        chat_interface = ChatInterface(
            config=st.session_state.config,
            session_id=st.session_state.session_id
        )
        
        # Process any queued WebSocket messages
        process_websocket_messages(chat_interface)
        
        # Render chat interface
        chat_interface.render()
        
    except ImportError as e:
        st.error(f"Failed to load chat interface: {e}")
        st.info("Make sure all dependencies are installed and services are running.")


def render_document_page():
    """Render document upload page"""
    st.header("📄 Document Management")
    
    try:
        from components.document_upload import DocumentUpload
        
        document_upload = DocumentUpload(
            config=st.session_state.config,
            session_id=st.session_state.session_id
        )
        
        document_upload.render()
        
    except ImportError:
        st.warning("Document upload component not yet implemented.")
        st.code("""
        # Placeholder for document upload interface
        # Will be implemented in next tasks:
        # - PDF URL submission form
        # - Upload progress monitoring
        # - Processing status tracking
        # - Document validation feedback
        """)


def render_dashboard_page():
    """Render system dashboard page"""
    st.header("📊 System Dashboard")
    
    try:
        from components.dashboard import Dashboard
        
        dashboard = Dashboard(
            config=st.session_state.config
        )
        
        dashboard.render()
        
    except ImportError:
        st.warning("Dashboard component not yet implemented.")
        
        # Placeholder metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Active Sessions", "0", delta="0")
        
        with col2:
            st.metric("Documents Processed", "0", delta="0")
        
        with col3:
            st.metric("Questions Asked", "0", delta="0")
        
        with col4:
            st.metric("System Uptime", "0s", delta="0")
        
        st.code("""
        # Placeholder for system dashboard
        # Will be implemented in next tasks:
        # - Real-time metrics visualization
        # - NATS topic activity monitoring
        # - Connection status indicators  
        # - Performance charts with Plotly
        """)


def render_settings_page():
    """Render settings page"""
    st.header("⚙️ Settings")
    
    with st.expander("Configuration", expanded=True):
        st.json(st.session_state.config)
    
    with st.expander("Session Information"):
        if st.session_state.session_id:
            st.json({
                'session_id': st.session_state.session_id,
                'nickname': st.session_state.session_nickname,
                'chat_history_length': len(st.session_state.chat_history),
                'document_jobs': len(st.session_state.document_jobs)
            })
        else:
            st.info("No active session")
    
    with st.expander("Debug Information"):
        st.code(f"""
        Script Run Context: {get_script_run_ctx()}
        Session State Keys: {list(st.session_state.keys())}
        Python Path: {sys.path[:3]}...
        Working Directory: {os.getcwd()}
        """)


def main():
    """Main application entry point"""
    try:
        # Configure page and initialize state
        configure_page()
        initialize_session_state()
        
        # Initial system status check
        if 'status_checked' not in st.session_state:
            check_system_status()
            st.session_state.status_checked = True
        
        # Render UI components
        render_header()
        render_sidebar()
        render_main_content()
        
        logger.info("Streamlit app rendered successfully")
        
    except Exception as e:
        logger.error(f"Application error: {e}")
        st.error(f"Application error: {str(e)}")
        
        if st.session_state.config.get('debug', False):
            st.exception(e)


if __name__ == "__main__":
    main()