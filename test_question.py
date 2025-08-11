#!/usr/bin/env python3
"""
Test sending a question to the RAG system and monitoring the answer
"""

import asyncio
import json
import uuid
from datetime import datetime
import nats

async def test_question():
    # Configuration
    NATS_URL = "nats://localhost:4222"
    session_id = str(uuid.uuid4())
    question = "quais as doenças que você conhece"
    
    print(f"🔗 Connecting to NATS at {NATS_URL}")
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    
    print(f"📝 Session ID: {session_id}")
    print(f"❓ Question: {question}")
    print("-" * 80)
    
    # Subscribe to the session-specific answer topic
    answer_topic = f"chat.answers.{session_id}"
    print(f"👂 Subscribing to answer topic: {answer_topic}")
    
    # Also try general chat answers pattern
    general_answer_topic = "chat.answers.*"
    print(f"👂 Also subscribing to general pattern: {general_answer_topic}")
    
    # Store received messages
    received_messages = []
    complete = asyncio.Event()
    
    async def message_handler(msg):
        """Handle answer messages"""
        try:
            data = json.loads(msg.data.decode())
            msg_type = data.get('type', 'unknown')
            
            print(f"\n📨 Received {msg_type} message:")
            
            if msg_type == 'chunk':
                content = data.get('content', '')
                print(f"   Content: {content}")
                received_messages.append(content)
                
            elif msg_type == 'error':
                print(f"   ❌ Error: {data.get('error', 'Unknown error')}")
                complete.set()
                
            elif msg_type == 'complete':
                print(f"   ✅ Answer complete!")
                print(f"   Total chunks received: {len(received_messages)}")
                complete.set()
                
            elif msg_type == 'metadata':
                print(f"   📊 Metadata:")
                metadata = data.get('metadata', {})
                print(f"      Sources: {metadata.get('sources', [])}")
                print(f"      Processing time: {metadata.get('processing_time', 'N/A')}")
                
            else:
                print(f"   Raw data: {data}")
                
            await msg.ack()
            
        except Exception as e:
            print(f"   ⚠️ Error processing message: {e}")
            print(f"   Raw: {msg.data}")
    
    # Subscribe to both answer topics
    sub1 = await nc.subscribe(answer_topic, cb=message_handler)
    sub2 = await nc.subscribe(general_answer_topic, cb=message_handler)
    
    # Create question message
    question_msg = {
        "session_id": session_id,
        "question": question,
        "timestamp": datetime.now().isoformat(),
        "metadata": {
            "language": "pt-BR",
            "max_chunks": 3,
            "temperature": 0.7
        }
    }
    
    # Publish question to the chat.questions topic (where the handler listens)
    print(f"\n📤 Sending question to 'chat.questions' topic...")
    await nc.publish("chat.questions", json.dumps(question_msg).encode())
    print(f"   Sent: {json.dumps(question_msg, indent=2)}")
    
    # Wait for complete message or timeout
    print(f"\n⏳ Waiting for answer (timeout: 30s)...")
    try:
        await asyncio.wait_for(complete.wait(), timeout=30.0)
        
        # Display full answer
        if received_messages:
            print("\n" + "=" * 80)
            print("COMPLETE ANSWER:")
            print("=" * 80)
            full_answer = "".join(received_messages)
            print(full_answer)
            print("=" * 80)
            
    except asyncio.TimeoutError:
        print("\n⏱️ Timeout waiting for answer")
        if received_messages:
            print("Partial answer received:")
            print("".join(received_messages))
    
    # Cleanup
    await sub1.unsubscribe()
    await sub2.unsubscribe()
    await nc.close()
    
    print(f"\n✅ Test complete")

if __name__ == "__main__":
    asyncio.run(test_question())