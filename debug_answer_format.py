#!/usr/bin/env python3
"""
Debug script to see the full format of answer messages
"""
import asyncio
import json
import nats

async def debug_messages():
    session_id = "7e6a7409-e7d4-477a-b794-0284a5b5afa4"
    
    nc = await nats.connect("nats://localhost:4222")
    
    async def message_handler(msg):
        print(f"📨 Full Message on {msg.subject}:")
        try:
            data = json.loads(msg.data.decode())
            print(json.dumps(data, indent=2))
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            print(f"Raw: {msg.data}")
        print("="*80)
        await msg.ack()
    
    await nc.subscribe(f"chat.answers.{session_id}", cb=message_handler)
    
    print("Listening for 15 seconds for detailed message format...")
    await asyncio.sleep(15)
    
    await nc.close()

if __name__ == "__main__":
    asyncio.run(debug_messages())