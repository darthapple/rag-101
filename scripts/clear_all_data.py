#!/usr/bin/env python3
"""
Clear all data from NATS and Milvus
Run this with worker STOPPED
"""

import asyncio
import nats
from pymilvus import connections, Collection, utility


async def clear_all_data():
    """Clear all data from NATS and Milvus"""
    print("🧹 Clearing all data (worker must be stopped)...")
    
    # Connect to NATS - use container name when running inside Docker
    nc = await nats.connect("nats://nats:4222")
    js = nc.jetstream()
    print("✅ Connected to NATS")
    
    # Delete all streams
    streams_to_delete = [
        "documents_download",
        "documents_chunks", 
        "documents_embeddings",
        "documents_complete"
    ]
    
    for stream_name in streams_to_delete:
        try:
            await js.delete_stream(stream_name)
            print(f"  ✅ Deleted stream: {stream_name}")
        except Exception as e:
            print(f"  ⚠️ Stream {stream_name} not found or error: {e}")
    
    # Clear NATS KV stores
    kv_buckets = ["sessions", "processing_status", "cache"]
    for bucket in kv_buckets:
        try:
            kv = await js.key_value(bucket)
            keys = await kv.keys()
            for key in keys:
                await kv.delete(key)
            print(f"  ✅ Cleared KV bucket: {bucket}")
        except Exception as e:
            print(f"  ⚠️ KV bucket {bucket} not found or error: {e}")
    
    await nc.close()
    print("✅ NATS cleared")
    
    # Clear Milvus - use container name when running inside Docker
    try:
        connections.connect("default", host='standalone', port='19530')
        
        if utility.has_collection("medical_documents"):
            collection = Collection("medical_documents")
            count = collection.num_entities
            collection.drop()
            print(f"✅ Dropped Milvus collection (had {count} documents)")
        else:
            print("ℹ️ No Milvus collection to drop")
            
        connections.disconnect("default")
        print("✅ Milvus cleared")
        
    except Exception as e:
        print(f"⚠️ Milvus error: {e}")
    
    print("\n✨ All data cleared! Ready to start fresh worker.")


if __name__ == "__main__":
    asyncio.run(clear_all_data())