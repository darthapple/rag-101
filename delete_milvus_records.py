#!/usr/bin/env python3
"""
Delete all records from Milvus medical_documents collection.
This script will drop the entire collection, removing all vector embeddings.
"""

import subprocess
import sys
import json

# Try to import pymilvus, install if not available
try:
    from pymilvus import Collection, connections, utility
except ImportError:
    print("Installing pymilvus...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "--break-system-packages", "pymilvus"])
    from pymilvus import Collection, connections, utility

def delete_all_records():
    """Delete all records from Milvus by dropping the collection"""
    
    # Connect to Milvus
    print("Connecting to Milvus at localhost:19530...")
    connections.connect("default", host="localhost", port="19530")
    
    collection_name = "medical_documents"
    
    try:
        # Check if collection exists
        if utility.has_collection(collection_name):
            print(f"Collection '{collection_name}' found")
            
            # Get collection to check record count
            collection = Collection(collection_name)
            
            # Get current count before deletion
            num_records = collection.num_entities
            print(f"Current records in collection: {num_records}")
            
            if num_records == 0:
                print("Collection is already empty")
                return {
                    "status": "success",
                    "message": "Collection was already empty",
                    "records_deleted": 0
                }
            
            # Drop the collection completely (this deletes all records)
            print(f"Dropping collection '{collection_name}'...")
            collection.drop()
            print(f"✅ Collection '{collection_name}' dropped successfully")
            
            return {
                "status": "success",
                "message": f"Successfully deleted all {num_records} records",
                "records_deleted": num_records
            }
            
        else:
            print(f"Collection '{collection_name}' does not exist")
            return {
                "status": "success",
                "message": "Collection does not exist",
                "records_deleted": 0
            }
            
    except Exception as e:
        error_msg = f"Error deleting Milvus records: {e}"
        print(f"❌ {error_msg}")
        return {
            "status": "error",
            "message": error_msg,
            "records_deleted": 0
        }
    finally:
        # Disconnect from Milvus
        connections.disconnect("default")
        print("Disconnected from Milvus")

if __name__ == "__main__":
    result = delete_all_records()
    print("\n" + "="*50)
    print("RESULT:")
    print(json.dumps(result, indent=2))
    
    # Exit with appropriate code
    sys.exit(0 if result["status"] == "success" else 1)