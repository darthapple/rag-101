# RAG-101 UI Service

Streamlit-based web interface for the RAG-101 medical document Q&A system.

## Features

- **Chat Interface**: Interactive Q&A interface with real-time answer streaming
- **Document Upload**: PDF document submission and processing management
- **Dashboard**: Real-time system monitoring and analytics
- **Session Management**: User session handling and persistence

## Architecture

- **Framework**: Streamlit for web UI
- **Real-time Communication**: WebSocket integration with API service
- **Data Visualization**: Plotly charts for system metrics
- **API Integration**: HTTP requests to FastAPI service

## Development

```bash
# Install dependencies
poetry install

# Run development server
poetry run streamlit run main.py --server.port 8501

# Run with Docker
docker build -t rag-101-ui .
docker run -p 8501:8501 rag-101-ui
```

## Environment Variables

- `API_BASE_URL`: FastAPI service URL (default: http://localhost:8000)
- `WS_BASE_URL`: WebSocket service URL (default: ws://localhost:8000)
- `NATS_URL`: NATS server URL for monitoring (default: nats://localhost:4222)
- `SESSION_TTL`: Session timeout in seconds (default: 3600)

## Components

### Chat Interface (`components/chat_interface.py`)
- Real-time question submission and answer streaming
- Message history and session context
- Markdown rendering for formatted responses

### Document Upload (`components/document_upload.py`)  
- PDF document URL submission
- Upload progress monitoring
- Processing status tracking

### Dashboard (`components/dashboard.py`)
- System metrics visualization
- NATS topic activity monitoring
- Connection status indicators

### Session Manager (`components/session_manager.py`)
- User session creation and management
- Session state persistence
- Authentication handling