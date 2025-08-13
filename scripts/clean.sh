#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}    RAG-101 System Cleanup Script      ${NC}"
echo -e "${GREEN}========================================${NC}"

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check if NATS CLI is installed
if ! command_exists nats; then
    echo -e "${RED}Error: NATS CLI is not installed or not in PATH${NC}"
    echo "Please install NATS CLI: https://docs.nats.io/using-nats/nats-tools/nats_cli"
    exit 1
fi

# Function to purge NATS streams
purge_nats_streams() {
    echo -e "\n${YELLOW}Purging NATS Streams...${NC}"
    
    local streams=(
        "chat_answers"
        "chat_questions"
        "system_metrics"
        "documents_download"
        "documents_embeddings"
        "documents_chunks"
    )
    
    for stream in "${streams[@]}"; do
        echo -n "  Purging stream: $stream... "
        if nats stream purge "$stream" -f >/dev/null 2>&1; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${YELLOW}skipped (may not exist)${NC}"
        fi
    done
}

# Function to clear NATS KV buckets
clear_nats_kv() {
    echo -e "\n${YELLOW}Clearing NATS KV Buckets...${NC}"
    
    local buckets=(
        "cache"
        "processing_status"
        "sessions"
    )
    
    for bucket in "${buckets[@]}"; do
        echo -n "  Deleting bucket: $bucket... "
        if nats kv del "$bucket" --force >/dev/null 2>&1; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${YELLOW}skipped (may not exist)${NC}"
        fi
    done
}

# Function to drop and recreate Milvus collection
reset_milvus_collection() {
    echo -e "\n${YELLOW}Resetting Milvus Collection...${NC}"
    
    # Python script to drop and recreate collection
    local python_script='
from pymilvus import connections, Collection, utility, FieldSchema, CollectionSchema, DataType
import sys

try:
    # Connect to Milvus
    connections.connect(host="standalone", port=19530)
    
    collection_name = "medical_documents"
    
    # Drop existing collection if it exists
    if utility.has_collection(collection_name):
        collection = Collection(collection_name)
        collection.drop()
        print("  Collection dropped successfully")
    else:
        print("  Collection does not exist")
    
    # Define schema for the collection
    fields = [
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, is_primary=True, max_length=100),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=768),
        FieldSchema(name="text_content", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="document_title", dtype=DataType.VARCHAR, max_length=500),
        FieldSchema(name="source_url", dtype=DataType.VARCHAR, max_length=1000),
        FieldSchema(name="page_number", dtype=DataType.INT64),
        FieldSchema(name="diseases", dtype=DataType.VARCHAR, max_length=2000),
        FieldSchema(name="processed_at", dtype=DataType.VARCHAR, max_length=100),
        FieldSchema(name="job_id", dtype=DataType.VARCHAR, max_length=100)
    ]
    
    # Create collection schema
    schema = CollectionSchema(
        fields=fields,
        description="Medical documents with embeddings"
    )
    
    # Create the collection
    collection = Collection(
        name=collection_name,
        schema=schema,
        consistency_level="Strong"
    )
    
    # Create index for vector field
    index_params = {
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128}
    }
    collection.create_index(
        field_name="embedding",
        index_params=index_params
    )
    
    print("  Collection recreated successfully")
    print("  Index created on embedding field")
    
    # Load collection into memory
    collection.load()
    print("  Collection loaded into memory")
    
except Exception as e:
    print(f"  Error: {e}")
    sys.exit(1)
'
    
    # Try to execute in worker container first, then API container
    if docker exec rag-101-worker python -c "$python_script" 2>/dev/null; then
        echo -e "${GREEN}  ✓ Milvus collection reset successfully${NC}"
    elif docker exec rag-101-api python -c "$python_script" 2>/dev/null; then
        echo -e "${GREEN}  ✓ Milvus collection reset successfully${NC}"
    else
        echo -e "${YELLOW}  ⚠ Could not reset Milvus collection (will be created on first use)${NC}"
    fi
}

# Function to verify cleanup
verify_cleanup() {
    echo -e "\n${YELLOW}Verifying Cleanup...${NC}"
    
    # Check NATS streams
    echo "  NATS Streams Status:"
    nats stream ls | grep -E "documents_|chat_|system_" | while read -r line; do
        if echo "$line" | grep -q "│ 0 "; then
            echo -e "    ${GREEN}✓${NC} Stream is empty"
        else
            echo -e "    ${YELLOW}⚠${NC} Stream may have messages"
        fi
    done
}

# Function to restart services
restart_services() {
    echo -e "\n${YELLOW}Restarting Services...${NC}"
    
    echo -n "  Restarting worker, api, and ui services... "
    if docker compose restart worker api ui >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        
        # Wait for services to be healthy
        echo -n "  Waiting for services to be healthy... "
        sleep 5
        
        # Check if services are running
        if docker compose ps | grep -q "healthy"; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${YELLOW}⚠ Services may still be starting${NC}"
        fi
    else
        echo -e "${RED}✗ Failed to restart services${NC}"
    fi
}

# Main execution
main() {
    # Check if Docker is running
    if ! docker info >/dev/null 2>&1; then
        echo -e "${RED}Error: Docker is not running${NC}"
        exit 1
    fi
    
    # Check if containers are running
    if ! docker compose ps | grep -q "rag-101"; then
        echo -e "${RED}Error: RAG-101 containers are not running${NC}"
        echo "Please run: docker compose up -d"
        exit 1
    fi
    
    # Execute cleanup steps
    purge_nats_streams
    clear_nats_kv
    reset_milvus_collection
    restart_services
    verify_cleanup
    
    echo -e "\n${GREEN}========================================${NC}"
    echo -e "${GREEN}    Cleanup Completed Successfully!     ${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo -e "\nThe system is now in a clean state and ready for use."
}

# Run main function
main "$@"