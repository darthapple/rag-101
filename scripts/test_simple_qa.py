#!/usr/bin/env python3
"""
Simple Q&A Test for RAG-101 API

Tests the core question/answer flow:
1. Create a session
2. Submit a question
3. Wait for answer via worker processing
4. Check if answer is generated

Usage: python test_simple_qa.py
"""

import asyncio
import json
import time
import httpx
import nats
from datetime import datetime


async def test_qa_flow():
    """Test the complete question/answer flow"""
    print("🧪 Starting Simple Q&A Test")
    print("=" * 50)
    
    base_url = "http://localhost:8000"
    nats_url = "nats://localhost:4222"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Create a session
        print("1. Creating test session...")
        session_response = await client.post(
            f"{base_url}/api/v1/sessions/",
            json={"nickname": "Test User QA"}
        )
        
        if session_response.status_code != 201:
            print(f"❌ Failed to create session: {session_response.status_code}")
            return
        
        session_data = session_response.json()
        session_id = session_data['session_id']
        print(f"✅ Created session: {session_id[:8]}...")
        
        # Step 2: Connect to NATS to listen for answers
        print("2. Connecting to NATS to monitor answers...")
        nc = await nats.connect(nats_url)
        js = nc.jetstream()
        
        answer_received = False
        answer_content = None
        
        async def answer_handler(msg):
            nonlocal answer_received, answer_content
            try:
                data = json.loads(msg.data.decode())
                print(f"📨 Received answer: {data}")
                answer_content = data
                answer_received = True
            except Exception as e:
                print(f"❌ Error parsing answer: {e}")
        
        # Subscribe to session-specific answer topic
        answer_topic = f"chat.answers.{session_id}"
        print(f"📡 Subscribing to: {answer_topic}")
        
        try:
            sub = await js.subscribe(answer_topic, cb=answer_handler)
        except Exception as e:
            print(f"❌ Failed to subscribe to answer topic: {e}")
            # Try alternative topic format
            answer_topic = f"answers.{session_id}"
            print(f"📡 Trying alternative topic: {answer_topic}")
            try:
                sub = await js.subscribe(answer_topic, cb=answer_handler)
            except Exception as e2:
                print(f"❌ Failed to subscribe to alternative topic: {e2}")
                await nc.close()
                return
        
        # Step 3: Submit a question
        print("3. Submitting test question...")
        question_response = await client.post(
            f"{base_url}/api/v1/questions/",
            json={
                "question": "What are clinical protocols and why are they important?",
                "session_id": session_id
            }
        )
        
        if question_response.status_code != 200:
            print(f"❌ Failed to submit question: {question_response.status_code}")
            print(f"Response: {question_response.text}")
            await nc.close()
            return
        
        question_data = question_response.json()
        question_id = question_data['question_id']
        print(f"✅ Submitted question: {question_id[:8]}...")
        
        # Step 4: Wait for answer
        print("4. Waiting for answer (30s timeout)...")
        start_wait = time.time()
        timeout = 30.0
        
        while time.time() - start_wait < timeout and not answer_received:
            await asyncio.sleep(1)
            print(f"⏳ Waiting... ({int(time.time() - start_wait)}s)")
        
        await nc.close()
        
        # Step 5: Results
        print("\n" + "=" * 50)
        print("🏁 TEST RESULTS")
        print("=" * 50)
        
        if answer_received:
            print("✅ SUCCESS: Received answer!")
            print(f"📄 Answer content: {json.dumps(answer_content, indent=2)}")
            print(f"⏱️  Response time: {time.time() - start_wait:.1f}s")
        else:
            print("❌ TIMEOUT: No answer received within 30 seconds")
            print("💡 This could mean:")
            print("   - Worker service is not processing questions")
            print("   - No documents are indexed for answering")
            print("   - NATS topic routing is incorrect")
            print("   - AI service (Gemini) is not responding")
        
        # Step 6: Cleanup
        print("\n5. Cleaning up session...")
        cleanup_response = await client.delete(f"{base_url}/api/v1/sessions/{session_id}")
        if cleanup_response.status_code == 200:
            print("✅ Session cleaned up successfully")
        else:
            print(f"⚠️  Session cleanup failed: {cleanup_response.status_code}")


async def check_system_status():
    """Check if all system components are healthy"""
    print("🔍 Checking System Status")
    print("=" * 50)
    
    base_url = "http://localhost:8000"
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{base_url}/health")
            if response.status_code == 200:
                data = response.json()
                print("✅ API Service: Healthy")
                
                infra = data.get('infrastructure', {})
                nats_status = infra.get('nats', {})
                milvus_status = infra.get('milvus', {})
                
                print(f"📡 NATS: {'✅ Connected' if nats_status.get('connected') else '❌ Disconnected'}")
                print(f"🔍 Milvus: {'✅ Connected' if milvus_status.get('connected') else '❌ Disconnected'}")
                print(f"📚 Documents indexed: {milvus_status.get('entities', 0)}")
                print(f"🔑 Gemini API: {'✅ Configured' if data.get('google_api_key_configured') else '❌ Not configured'}")
                
                return True
            else:
                print(f"❌ API Service: Unhealthy (HTTP {response.status_code})")
                return False
        except Exception as e:
            print(f"❌ API Service: Connection failed - {e}")
            return False


async def main():
    """Main test function"""
    print("🚀 RAG-101 Simple Q&A Test")
    print("🕒 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)
    
    # First check if system is healthy
    if await check_system_status():
        print("\n" + "=" * 60)
        await test_qa_flow()
    else:
        print("\n❌ System not healthy - skipping Q&A test")
        print("💡 Make sure Docker services are running: docker compose up -d")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"\n💥 Test failed with error: {e}")