# Scripts

This directory contains utility scripts for managing the RAG-101 system.

## clean.sh

A comprehensive cleanup script that resets the entire RAG-101 system to a fresh state.

### What it does:

1. **Purges all NATS streams:**
   - `chat_answers` - Session-specific answer delivery
   - `chat_questions` - User questions for processing  
   - `system_metrics` - System monitoring data
   - `documents_download` - PDF download requests
   - `documents_embeddings` - Embedding generation requests
   - `documents_chunks` - Document chunking requests

2. **Clears NATS KV buckets:**
   - `cache` - Temporary cache data
   - `processing_status` - Processing status tracking
   - `sessions` - Session management data

3. **Resets Milvus collection:**
   - Drops the existing `medical_documents` collection
   - Recreates it with the proper schema
   - Creates the vector index for similarity search
   - Loads the collection into memory

4. **Restarts services:**
   - Restarts worker, API, and UI services
   - Waits for services to become healthy

5. **Verifies cleanup:**
   - Confirms all streams are empty
   - Checks service status

### Usage:

```bash
# From the project root directory
./scripts/clean.sh
```

### Prerequisites:

- Docker and Docker Compose must be running
- RAG-101 containers must be started (`docker compose up -d`)
- NATS CLI must be installed and available in PATH

### When to use:

- Before testing new document processing
- When you want to clear all processed data
- After encountering data corruption issues
- When debugging requires a clean state
- Before demonstrations

### Output:

The script provides colorized output showing:
- ✅ Successful operations in green
- ⚠️ Warnings in yellow  
- ❌ Errors in red

All operations are logged with clear status indicators.