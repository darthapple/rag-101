#!/usr/bin/env python3
import sys
sys.path.append("/Users/fadriano/Projetos/Demos/rag-101")
from pymilvus import Collection, connections, utility

# Connect to Milvus
connections.connect("default", host="localhost", port="19530")

collection_name = "medical_documents"

try:
    # Check if collection exists
    if utility.has_collection(collection_name):
        print(f"Collection '{collection_name}' exists")
        
        # Get collection
        collection = Collection(collection_name)
        
        # Check current count
        print(f"Current documents: {collection.num_entities}")
        
        # Drop the collection completely
        collection.drop()
        print(f"Collection '{collection_name}' dropped successfully")
    else:
        print(f"Collection '{collection_name}' does not exist")
        
except Exception as e:
    print(f"Error clearing Milvus: {e}")

print("Milvus cleared!")