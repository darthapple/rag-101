#!/usr/bin/env python3
"""
Monitor NATS topics to see message flow
"""

import asyncio
import json
from datetime import datetime
import nats

async def monitor():
    nc = await nats.connect("nats://localhost:4222")
    
    print("🔍 Monitoring NATS topics...")
    print("-" * 80)
    
    # Topics to monitor
    topics = [
        "questions",
        "answers.*",
        "chat.questions",
        "chat.answers",
        "documents.download",
        "documents.chunks", 
        "embeddings.create",
        "system.metrics"
    ]
    
    async def handler(msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        topic = msg.subject
        try:
            data = json.loads(msg.data.decode())
            print(f"[{timestamp}] 📨 {topic}")
            print(f"   Data: {json.dumps(data, indent=2)[:500]}")
        except:
            print(f"[{timestamp}] 📨 {topic}")
            print(f"   Raw: {msg.data[:200]}")
        print("-" * 40)
    
    # Subscribe to all topics
    for topic in topics:
        await nc.subscribe(topic, cb=handler)
        print(f"✅ Subscribed to: {topic}")
    
    print("\n📡 Listening for messages... (Press Ctrl+C to stop)\n")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    
    await nc.close()

if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        print("\n👋 Stopped monitoring")