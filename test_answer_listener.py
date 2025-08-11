#!/usr/bin/env python3
"""
Test script to listen for answers on NATS topics
"""
import asyncio
import json
import uuid
from datetime import datetime
import nats

async def test_answer_listener():
    session_id = "7e6a7409-e7d4-477a-b794-0284a5b5afa4"
    
    print(f"🔗 Connecting to NATS...")
    nc = await nats.connect("nats://localhost:4222")
    
    print(f"👂 Listening for answers...")
    print(f"   Session-specific topic: chat.answers.{session_id}")
    print(f"   Wildcard topic: chat.answers.*")
    print("-" * 80)
    
    message_count = 0
    
    async def message_handler(msg):
        nonlocal message_count
        message_count += 1
        
        print(f"📨 Message #{message_count} received:")
        print(f"   Subject: {msg.subject}")
        
        try:
            data = json.loads(msg.data.decode())
            print(f"   Data keys: {list(data.keys())}")
            
            if 'answer' in data:
                print(f"   📝 ANSWER: {data['answer'][:100]}...")
                if len(data['answer']) > 100:
                    print(f"   (Answer truncated, full length: {len(data['answer'])} chars)")
            
            if 'sources' in data:
                print(f"   📚 Sources: {len(data.get('sources', []))} documents")
                
            if 'processing_time' in data:
                print(f"   ⏱️ Processing time: {data['processing_time']}s")
                
        except Exception as e:
            print(f"   ⚠️ Error parsing JSON: {e}")
            print(f"   Raw data: {msg.data[:200]}...")
        
        print("-" * 40)
        await msg.ack()
    
    # Subscribe to both specific and wildcard topics
    sub1 = await nc.subscribe(f"chat.answers.{session_id}", cb=message_handler)
    sub2 = await nc.subscribe("chat.answers.*", cb=message_handler)
    
    print("🚀 Listeners active! Submit a question now...")
    print("   Listening for 30 seconds...")
    
    # Listen for 30 seconds
    for i in range(30):
        await asyncio.sleep(1)
        if i % 5 == 4:  # Print status every 5 seconds
            print(f"   Still listening... {30-i-1}s remaining")
    
    print(f"\n📊 Summary:")
    print(f"   Total messages received: {message_count}")
    
    # Cleanup
    await sub1.unsubscribe()
    await sub2.unsubscribe()
    await nc.close()
    
    print("✅ Test completed")

if __name__ == "__main__":
    asyncio.run(test_answer_listener())