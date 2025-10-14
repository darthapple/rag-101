# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a complete **Retrieval Augmented Generation (RAG)** system for medical document Q&A based on Brazilian clinical protocols (PCDT). The system uses a modern ephemeral messaging architecture with real-time processing and vector search capabilities.

## Architecture

The system implements an **ephemeral/vector architecture** with two main data layers:

1. **Ephemeral Layer (NATS)**: All processing data expires automatically via TTL (1 hour default)
2. **Persistent Layer (Milvus)**: Only vector embeddings persist for semantic search

### Core Components
- **Vector Database**: Milvus for fast similarity search (< 100ms)
- **Message Streaming**: NATS JetStream for ephemeral processing with TTL-based cleanup
- **AI Integration**: Google Gemini for embeddings (text-embedding-004) and text generation (gemini-pro)
- **Worker Services**: Python background processors for documents, embeddings, and Q&A
- **API Service**: FastAPI with WebSocket support for real-time answers
- **UI Service**: Streamlit with live dashboard showing message flows

## Development Setup

### Prerequisites
- Docker & Docker Compose (required for infrastructure)
- Python 3.11+ with Poetry (for local development)
- Google Gemini API key

### Quick Start Commands

```bash
# 1. Start infrastructure services (Milvus, NATS, etcd, MinIO)
docker-compose up -d

# 2. Set up environment
export GEMINI_API_KEY=your_api_key_here
export MILVUS_HOST=localhost
export MILVUS_PORT=19530
export NATS_URL=nats://localhost:4222

# 3. Development workflow (choose a service to work on)
cd services/worker  # or services/api or services/ui
poetry install
poetry shell
poetry run python main.py  # or appropriate start command
```

### Full Production Deployment
```bash
# Create .env file with GEMINI_API_KEY
echo "GEMINI_API_KEY=your_key_here" > .env

# Deploy all services (IMPORTANT: only use docker-compose.yml)
docker-compose up --build
```

### Service Access
- **Chat Interface**: http://localhost:8501 (Streamlit UI)
- **API Documentation**: http://localhost:8000/docs (FastAPI)
- **NATS Monitoring**: http://localhost:8222 (JetStream stats)
- **MinIO Console**: http://localhost:9001 (Milvus storage)

## Development Commands

**Note**: The services directory structure is documented in the PRD but may not exist yet. When implementing:

```bash
# Worker service (document processing, embeddings, Q&A)
cd services/worker
poetry run python main.py

# API service (FastAPI with WebSocket support)
cd services/api  
poetry run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# UI service (Streamlit with real-time dashboard)
cd services/ui
poetry run streamlit run main.py --server.port 8501

# Testing (when implemented)
poetry run pytest                    # All tests
poetry run pytest -m unit          # Unit tests only
poetry run pytest -m integration   # Integration tests
poetry run pytest --cov=services   # With coverage
```

## Key Architecture Patterns

### Message Flow Patterns
1. **Document Processing**: URL → Download → Chunking → Embedding → Vector Storage
2. **Q&A Flow**: Session Creation → Question → RAG Pipeline → Real-time Answer via WebSocket
3. **Session-based Routing**: Answers route to `answers.{session_id}` topics
4. **Ephemeral Processing**: All intermediate data expires in 1 hour

### Data Persistence Strategy
- **Milvus Collections**: Only vector embeddings with metadata persist
- **NATS Messages**: All processing messages are ephemeral (TTL-based cleanup)
- **Session Management**: Stored in NATS KV with automatic expiration
- **No Traditional Database**: System is stateless except for vectors

### Real-time Features
- **WebSocket Streaming**: Live answer delivery to specific sessions
- **Dashboard Monitoring**: Real-time visualization of NATS topic activity
- **Message TTL**: Automatic cleanup prevents data accumulation
- **Live Processing Status**: Visual indicators for document indexing progress

## Configuration

### Required Environment Variables
```bash
GEMINI_API_KEY=your_gemini_api_key     # Required for AI functionality
NATS_URL=nats://localhost:4222         # Message broker connection
MILVUS_HOST=localhost                  # Vector database host
MILVUS_PORT=19530                      # Vector database port
```

### Key Optional Settings
```bash
# TTL Settings (default: 3600 seconds)
SESSION_TTL=3600                       # Session expiration
MESSAGE_TTL=3600                       # Message expiration

# Worker Concurrency (default: 2 each)
MAX_DOCUMENT_WORKERS=2                 # Document processing concurrency
MAX_EMBEDDING_WORKERS=2                # Embedding generation concurrency
MAX_QUESTION_WORKERS=2                 # Q&A processing concurrency

# AI Configuration
EMBEDDING_MODEL=text-embedding-004     # Gemini embedding model
CHAT_MODEL=gemini-pro                  # Gemini text generation model
VECTOR_DIMENSION=768                   # Embedding dimension
```

## System Integration

### Milvus Vector Database
- **Collection**: `medical_documents` with 768-dimensional embeddings
- **Schema**: chunk_id (primary), embedding (vector), text_content, document_title, source_url, page_number, diseases, processed_at, job_id
- **Index**: IVF_FLAT with COSINE similarity for fast text retrieval
- **Performance**: Sub-100ms similarity search for top-K results

### NATS Messaging Topics
- **questions**: User questions for processing
- **answers.{session_id}**: Session-specific answer delivery
- **documents.download**: PDF processing requests
- **embeddings.create**: Chunk embedding generation
- **system.metrics**: Dashboard monitoring data
- **sessions**: NATS KV store for session management

### LangChain Integration
- **Document Processing**: RecursiveCharacterTextSplitter with 1000 char chunks, 200 overlap
- **Embeddings**: GoogleGenerativeAIEmbeddings with text-embedding-004
- **Generation**: ChatGoogleGenerativeAI with gemini-pro
- **RAG Chain**: Milvus vector store integration for retrieval

## Testing Strategy

When implementing tests, focus on:
- **Vector Operations**: Milvus schema validation and similarity search
- **Message Flows**: NATS pub/sub patterns and TTL behavior
- **RAG Pipeline**: End-to-end document processing and Q&A workflows
- **WebSocket Integration**: Real-time answer delivery and session management
- **Performance**: Vector search latency and concurrent processing

### Testing Commands

Use these commands for systematic testing and debugging. Helper scripts are available in the `scripts/` directory.

#### System State Management
```bash
# Comprehensive cleanup (NATS streams, KV buckets, Milvus collection)
bash scripts/clean.sh

# Python alternative (clears NATS + Milvus)
python scripts/clear_all_data.py

# Or run via Docker
docker exec rag-101-api python /app/scripts/clear_all_data.py
```

#### Database Inspection
```bash
# Check Milvus database - detailed view with statistics
python scripts/check_milvus.py

# Quick status check only
python scripts/check_milvus.py --simple

# Check via Docker (useful inside containers)
docker exec rag-101-worker python -c "
from pymilvus import connections, Collection
connections.connect('default', host='standalone', port='19530')
col = Collection('medical_documents')
col.load()
print(f'Documents: {col.num_entities}')
"
```

#### System Monitoring
```bash
# Monitor NATS streams
nats stream ls --server=nats://localhost:4222

# Detailed stream info
nats stream info documents_download --server=nats://localhost:4222
nats stream info documents_chunks --server=nats://localhost:4222
nats stream info documents_embeddings --server=nats://localhost:4222
nats stream info documents_complete --server=nats://localhost:4222

# Real-time message flow monitoring
python scripts/monitor_flow.py
```

#### Testing & Validation
```bash
# Full API test suite (comprehensive)
python scripts/test_api_comprehensive.py

# Simple Q&A flow test (quick validation)
python scripts/test_simple_qa.py

# Document processing tests
python scripts/submit_test_document.py      # Submit test document
python scripts/test_document_flow.py        # End-to-end document flow
python scripts/small_test.py                # Quick test
```

#### Single Handler Debugging
```bash
# Read message format from embeddings queue (uses ephemeral consumer to avoid interfering)
docker exec rag-101-api python -c "
import asyncio, nats
async def read_message():
    nc = await nats.connect('nats://nats:4222')
    js = nc.jetstream()
    try:
        # Use ephemeral consumer (no durable_name) to avoid competing with workers
        psub = await js.pull_subscribe('documents.embeddings')
        msgs = await psub.fetch(1, timeout=5.0)
        if msgs:
            print('Sample message format:')
            print(msgs[0].data.decode('utf-8'))
            # IMPORTANT: Do not ACK - let the actual worker process it
        else: print('No messages in queue')
        await psub.unsubscribe()
    except Exception as e: print(f'Error: {e}')
    await nc.close()
asyncio.run(read_message())
"

# Send single test message to embeddings queue
# (Replace MESSAGE_JSON with actual message format from above)
docker exec rag-101-api python -c "
import asyncio, nats, json
async def send_test_message():
    nc = await nats.connect('nats://nats:4222')
    test_msg = {
        'job_id': 'test-embedding-debug',
        'chunk_id': 'test-chunk-1',
        'text_content': 'This is a test chunk for embedding generation.',
        'document_title': 'Test Document',
        'source_url': 'test://debug',
        'page_number': 1
    }
    await nc.publish('documents.embeddings', json.dumps(test_msg).encode())
    print('Test message sent to embeddings queue')
    await nc.close()
asyncio.run(send_test_message())
"

# Monitor worker logs in real-time
docker logs rag-101-worker --follow
```

## Monitoring & Operations

### Health Checks
```bash
# Infrastructure health
curl http://localhost:8222/jsz        # NATS JetStream status
curl http://localhost:9001            # MinIO console (Milvus storage)

# Application health (when implemented)
curl http://localhost:8000/health     # API service health
curl http://localhost:8501            # UI service health
```

### Development vs Production
- **Development**: Poetry virtual environments, hot reloading, debug logging, 5-minute TTLs
- **Production**: Docker containers, stable deployment, info logging, 1-hour TTLs

### System Reset
```bash
# Complete reset (demo/development)
docker-compose down -v                # Removes all volumes including vectors
docker-compose up -d                  # Fresh start

# Soft reset (preserve vectors, reset processing state)
docker-compose restart worker api ui  # Keep Milvus data intact
```

## Project Structure (Expected)

```
services/
├── worker/           # Background processing (PDF, embeddings, Q&A)
│   ├── main.py       # Worker application entry point
│   └── handlers/     # Document, embedding, and answer handlers
├── api/              # FastAPI service with WebSocket support
│   ├── main.py       # FastAPI application entry point
│   └── routers/      # Session, question, and document endpoints
└── ui/               # Streamlit interface with real-time dashboard
    ├── main.py       # Streamlit application entry point
    └── components/   # Chat, document upload, and dashboard components

shared/               # Common utilities across services
├── database.py       # Milvus operations
├── messaging.py      # NATS operations
├── models.py         # Shared data models
└── config.py         # Configuration management

scripts/              # Testing and debugging utilities
├── check_milvus.py            # Database inspection (unified)
├── clean.sh                   # Comprehensive system cleanup
├── clear_all_data.py          # Python cleanup alternative
├── monitor_flow.py            # Real-time message flow monitoring
├── test_api_comprehensive.py  # Full API test suite
├── test_simple_qa.py          # Quick Q&A validation
├── submit_test_document.py    # Submit test documents
├── test_document_flow.py      # End-to-end document flow test
├── small_test.py              # Quick test runner
├── health-check.sh            # Service health verification
└── wait-for-services.sh       # Service startup coordination
```

## Important Notes for Implementation

- **Ephemeral Design**: All processing data is temporary - design for stateless recovery
- **Session-based Architecture**: All operations require valid session_id except health/docs
- **Real-time Focus**: WebSocket integration is core to user experience
- **Resource Constraints**: Optimized for notebook/demo environments with limited resources
- **Error Handling**: Keep simple for demo - focus on happy path scenarios
- **TTL-based Cleanup**: System self-cleans - no manual maintenance required

This system demonstrates modern RAG architecture patterns with real-time processing, ephemeral messaging, and efficient vector search.

## Task Master AI Instructions
**Import Task Master's development workflow commands and guidelines, treat as if import is in the main CLAUDE.md file.**
@./.taskmaster/CLAUDE.md
