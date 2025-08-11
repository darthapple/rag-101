#!/usr/bin/env python3
import sys
sys.path.append("/Users/fadriano/Projetos/Demos/rag-101")
from pymilvus import Collection, connections

# Connect to Milvus
connections.connect("default", host="localhost", port="19530")

# Get collection
collection = Collection("medical_documents")
collection.load()

# Get stats
stats = collection.num_entities
print(f"Total documents in collection: {stats}")

# Query all documents
results = collection.query(
    expr='chunk_id != ""',
    output_fields=["chunk_id", "document_title", "source_url", "text_content", "job_id"],
    limit=10
)

print(f"\nFound {len(results)} documents:")
for i, doc in enumerate(results, 1):
    print(f"\n{i}. Chunk ID: {doc['chunk_id']}")
    print(f"   Job ID: {doc.get('job_id', 'N/A')}")
    print(f"   Title: {doc.get('document_title', 'N/A')}")
    print(f"   URL: {doc.get('source_url', 'N/A')}")
    text = doc.get("text_content", "")
    if text:
        print(f"   Text preview: {text[:100]}...")