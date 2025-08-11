# RAG-101 Worker Service

Background processing service for the RAG-101 medical Q&A system. Handles document processing, embedding generation, and Q&A processing using an ephemeral messaging architecture.

## Architecture

The Worker service implements a multiprocessing architecture with specialized handlers:

- **Document Handler**: Downloads and processes PDF documents, creates text chunks
- **Embedding Handler**: Generates vector embeddings using Google Gemini
- **Q&A Handler**: Processes questions and generates answers using RAG pipeline

## Key Features

- **Ephemeral Processing**: All data expires automatically via TTL
- **Concurrent Processing**: Multiprocessing for scalable workload handling  
- **NATS Messaging**: JetStream integration for reliable message processing
- **Vector Storage**: Milvus integration for high-performance similarity search
- **AI Integration**: Google Gemini for embeddings and text generation

## Quick Start

```bash
# Install dependencies
poetry install

# Run the worker service
poetry run worker

# Or run with Python
poetry run python -m worker.main
```

## Configuration

The service uses environment variables for configuration:

```bash
# Required
GEMINI_API_KEY=your_gemini_api_key

# Optional (defaults provided)
NATS_URL=nats://localhost:4222
MILVUS_HOST=localhost
MILVUS_PORT=19530
MAX_DOCUMENT_WORKERS=2
MAX_EMBEDDING_WORKERS=2
MAX_QUESTION_WORKERS=2
```

## Development

```bash
# Install development dependencies
poetry install --with dev

# Run tests
poetry run pytest

# Format code
poetry run black .
poetry run ruff check .

# Type checking
poetry run mypy .
```

## Docker

```bash
# Build image
docker build -t rag-worker .

# Run container
docker run -e GEMINI_API_KEY=your_key rag-worker
```

## Message Processing

The worker subscribes to NATS JetStream topics:

- `documents.download` - Document processing requests
- `embeddings.create` - Embedding generation tasks
- `questions` - Question processing requests

Results are published to:
- `embeddings.complete` - Completed embeddings
- `answers.{session_id}` - Generated answers for specific sessions