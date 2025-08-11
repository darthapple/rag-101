#!/usr/bin/env python3
"""
Minimal Milvus checker - requires only: pip3 install pymilvus
Can be run from anywhere with: python3 check_milvus_simple.py
"""

try:
    from pymilvus import connections, Collection
    
    # Connect
    connections.connect('default', host='localhost', port='19530')
    
    # Get collection
    col = Collection('medical_documents')
    col.load()
    
    print(f"✅ Milvus connected")
    print(f"📊 Documents in database: {col.num_entities}")
    
    if col.num_entities > 0:
        # Get sample
        results = col.query(expr='chunk_id != ""', output_fields=['document_title', 'text_content'], limit=1)
        if results:
            print(f"\n📄 Sample document: {results[0].get('document_title', 'N/A')}")
            text = results[0].get('text_content', '')[:200]
            print(f"   Text preview: {text}...")
    
    connections.disconnect('default')
    
except ImportError:
    print("❌ pymilvus not installed. Run: pip3 install pymilvus")
except Exception as e:
    print(f"❌ Error: {e}")
    print("Make sure Milvus is running: docker compose up -d")