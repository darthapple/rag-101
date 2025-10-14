#!/usr/bin/env python3
"""
Submit test document to RAG-101 system for batch processing verification
"""

import json
import asyncio
import nats

async def submit_document():
    """Submit document directly to NATS queue"""
    
    # Document URL to test
    test_url = "https://www.gov.br/saude/pt-br/assuntos/pcdt/a/artrite-reumatoide-e-artrite-idiopatica-juvenil-portaria-conjunta-no-16/@@download/file"
    
    # Connect to NATS
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    
    # Create message payload for document download
    message_data = {
        "handler": "document-handler",
        "url": test_url,
        "session_id": "test-batch-session",
        "job_id": f"test-batch-{int(asyncio.get_event_loop().time())}",
        "processed_at": "2025-08-28T10:00:00Z"
    }
    
    # Publish to document download topic
    message_json = json.dumps(message_data).encode('utf-8')
    
    print(f"📤 Submitting document: {test_url}")
    print(f"🆔 Job ID: {message_data['job_id']}")
    
    await js.publish("documents.download", message_json)
    
    print("✅ Document submitted successfully!")
    print("📊 You can now monitor the processing with:")
    print("   python3 monitor_nats.py")
    
    await nc.close()

if __name__ == "__main__":
    asyncio.run(submit_document())