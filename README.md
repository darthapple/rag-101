# RAG 101: Medical Document Q&A System

A complete **Retrieval Augmented Generation (RAG)** system that answers questions about illnesses based on Brazilian clinical protocols. This project demonstrates modern RAG architecture using real-time messaging, vector search, and AI-powered question answering.

## What This System Does

- **📚 Document Processing**: Automatically downloads and indexes PDF documents from clinical protocols
- **🔍 Smart Search**: Uses vector embeddings to find relevant medical information
- **💬 Real-time Chat**: Ask questions and get instant answers with source citations
- **📊 Live Dashboard**: Watch document processing and question answering in real-time
- **🏥 Medical Focus**: Specifically designed for Brazilian clinical protocols (PCDT)

## Key Features

### Real-time Architecture
- **Instant Responses**: WebSocket-based chat with live answer streaming
- **Visual Monitoring**: Watch messages flow through the system in real-time
- **Ephemeral Processing**: All intermediate data expires automatically (privacy-focused)

### Modern Tech Stack
- **Vector Database**: Milvus for fast similarity search
- **Message Streaming**: NATS for real-time communication
- **AI Integration**: Google Gemini for embeddings and text generation
- **Web Interface**: Streamlit for interactive user experience
- **API-First**: FastAPI for robust backend services

### Production-Ready Features
- **Docker Deployment**: Complete containerized setup
- **Health Monitoring**: Built-in health checks and metrics
- **Session Management**: User sessions with automatic cleanup
- **Error Handling**: Graceful degradation and logging

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Google Gemini API key
- Python 3.11+ (for development)

### 1. Clone and Setup
```bash
git clone https://github.com/darthapple/rag-101.git
cd rag-101
```

### 2. Configure API Key
```bash
# Create environment file
echo "GOOGLE_API_KEY=your_gemini_api_key_here" > .env
```

### 3. Start the System
```bash
# Start infrastructure (Milvus, NATS)
docker-compose up -d

# Start all services
docker-compose -f docker-compose.yml -f docker-compose.services.yml up --build
```

### 4. Use the System
- **Chat Interface**: http://localhost:8501
- **API Documentation**: http://localhost:8000/docs
- **System Monitoring**: Built into the chat interface

## How It Works

1. **Upload Documents**: Paste PDF URLs from clinical protocols
2. **Automatic Processing**: System downloads, chunks, and creates embeddings
3. **Ask Questions**: Type medical questions in natural language
4. **Get Answers**: Receive AI-generated responses with source citations
5. **Real-time Feedback**: Watch the entire process on the dashboard

## Architecture Overview

```
User Interface (Streamlit)
        ↓
API Layer (FastAPI)
        ↓
Message Queue (NATS) ← Real-time Dashboard
        ↓
Worker Services (Python)
        ↓
Vector Database (Milvus) + AI Models (Gemini)
```

The system uses **ephemeral messaging** - all processing data expires automatically, ensuring privacy while maintaining fast performance.

## Development Setup

For development, you can run services locally while using Docker for infrastructure:

```bash
# Start infrastructure only
docker-compose up -d

# Run a service locally (example: worker)
cd services/worker
poetry install
poetry shell
python main.py
```

## Project Structure

- `services/worker/` - Background processing (PDF download, embeddings)
- `services/api/` - FastAPI web service and WebSocket management
- `services/ui/` - Streamlit user interface with real-time dashboard
- `shared/` - Common utilities and configurations
- `docs/PRD.md` - Complete technical documentation

## Documentation

- **[Complete PRD](docs/PRD.md)**: Full technical specification
- **API Docs**: Available at `/docs` when running
- **Configuration**: Extensive environment variable documentation
- **Testing**: Unit, integration, and performance test examples

## Use Cases

- **Medical Education**: Learn about clinical protocols interactively
- **Healthcare Research**: Quick access to protocol information
- **RAG Learning**: Understand modern RAG architecture patterns
- **System Integration**: Example of real-time AI-powered systems

## Technology Highlights

- **Vector Search**: Sub-100ms similarity search with Milvus
- **Real-time Processing**: NATS JetStream with TTL-based cleanup  
- **Modern Python**: FastAPI, LangChain, Poetry, async/await
- **Container-First**: Docker Compose for easy deployment
- **AI Integration**: Google Gemini for state-of-the-art embeddings and generation

This project serves as both a **practical medical Q&A system** and a **comprehensive RAG implementation example** for developers learning modern AI architectures.
