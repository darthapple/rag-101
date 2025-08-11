#!/usr/bin/env python3
import sys
sys.path.append("/Users/fadriano/Projetos/Demos/rag-101")
from pymilvus import Collection, connections
from collections import Counter

# Connect to Milvus
connections.connect("default", host="localhost", port="19530")

# Get collection
collection = Collection("medical_documents")
collection.load()

# Get all job IDs and count chunks per job
results = collection.query(
    expr='chunk_id != ""',
    output_fields=["chunk_id", "job_id"],
    limit=1000  # Get more results
)

print(f"Total documents in collection: {collection.num_entities}")
print(f"Retrieved {len(results)} documents for analysis\n")

# Count chunks per job
job_counts = Counter()
for doc in results:
    job_id = doc.get('job_id', 'unknown')
    job_counts[job_id] += 1

print("Chunks per job:")
for job_id, count in job_counts.most_common():
    print(f"  {job_id}: {count} chunks")
    
    # Show first few chunk IDs for this job
    job_chunks = [doc['chunk_id'] for doc in results if doc.get('job_id') == job_id][:5]
    for chunk_id in job_chunks:
        print(f"    - {chunk_id}")
    if len(job_chunks) >= 5:
        remaining = sum(1 for doc in results if doc.get('job_id') == job_id) - 5
        if remaining > 0:
            print(f"    ... and {remaining} more")
    print()