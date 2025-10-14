#!/usr/bin/env python3
"""
Simple monitoring script for document flow
Just sends a message and monitors - doesn't manage infrastructure
"""

import asyncio
import json
import time
import uuid
from datetime import datetime

import nats
from pymilvus import connections, Collection, utility


class FlowMonitor:
    def __init__(self):
        self.nc = None
        self.js = None
        self.test_url = "https://www.gov.br/saude/pt-br/assuntos/pcdt/a/artrite-reumatoide-e-artrite-idiopatica-juvenil-portaria-conjunta-no-16/@@download/file"
        self.job_id = str(uuid.uuid4())
        self.session_id = "test-" + str(uuid.uuid4())[:8]
        
    async def connect(self):
        """Connect to NATS and Milvus"""
        # Connect to NATS - use container names
        self.nc = await nats.connect("nats://nats:4222")
        self.js = self.nc.jetstream()
        print("✅ Connected to NATS")
        
        # Connect to Milvus - use container names
        connections.connect("default", host='standalone', port='19530')
        print("✅ Connected to Milvus")
        
    async def get_stats(self):
        """Get current queue and Milvus stats"""
        stats = {}
        
        # Check NATS streams
        streams = ["documents_download", "documents_chunks", "documents_embeddings", "documents_complete"]
        for stream_name in streams:
            try:
                info = await self.js.stream_info(stream_name)
                stats[stream_name] = info.state.messages
            except:
                stats[stream_name] = 0
        
        # Check Milvus
        try:
            if utility.has_collection("medical_documents"):
                collection = Collection("medical_documents")
                stats["milvus"] = collection.num_entities
            else:
                stats["milvus"] = 0
        except:
            stats["milvus"] = 0
            
        return stats
    
    async def send_document(self):
        """Send document URL to download queue"""
        print(f"\n📤 Sending document to download queue...")
        print(f"  URL: {self.test_url[:60]}...")
        print(f"  Job ID: {self.job_id}")
        
        message = {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "url": self.test_url,
            "timestamp": datetime.now().isoformat()
        }
        
        await self.js.publish("documents.download", json.dumps(message).encode())
        print("  ✅ Message sent")
        
    async def monitor(self):
        """Monitor the flow"""
        print("\n📊 Monitoring document flow...")
        print("  Expected flow:")
        print("    download: 0→1→0")
        print("    chunks: 0→1→0 (Milvus stays 0)")
        print("    embeddings: 0→706→0")
        print("    complete: 0→706→0 (Milvus 0→706)")
        print("\n  Time | Download | Chunks | Embeddings | Complete | Milvus")
        print("  -----|----------|--------|------------|----------|-------")
        
        start_time = time.time()
        last_stats = None
        stuck_count = 0
        max_wait = 300  # 5 minutes
        
        while True:
            await asyncio.sleep(2)
            
            stats = await self.get_stats()
            elapsed = int(time.time() - start_time)
            
            # Print status line
            print(f"  {elapsed:4d}s | {stats['documents_download']:8d} | {stats['documents_chunks']:6d} | {stats['documents_embeddings']:10d} | {stats['documents_complete']:8d} | {stats['milvus']:6d}")
            
            # Check if processing is complete
            if (stats['documents_download'] == 0 and 
                stats['documents_chunks'] == 0 and
                stats['documents_embeddings'] == 0 and
                stats['documents_complete'] == 0 and
                stats['milvus'] > 0):
                
                print(f"\n✅ Processing complete!")
                print(f"  Final Milvus count: {stats['milvus']}")
                
                if stats['milvus'] == 706:
                    print("  🎉 SUCCESS: All 706 chunks stored!")
                else:
                    print(f"  ⚠️ WARNING: Expected 706, got {stats['milvus']}")
                break
            
            # Detect stuck
            if stats == last_stats:
                stuck_count += 1
                if stuck_count > 30:  # 60 seconds
                    print("\n⚠️ Processing appears stuck")
                    # Don't break, keep monitoring
            else:
                stuck_count = 0
            last_stats = stats
            
            # Timeout
            if elapsed > max_wait:
                print(f"\n⏱️ Timeout after {elapsed} seconds")
                print(f"  Final state: {stats}")
                break
    
    async def run(self):
        """Run the monitoring"""
        try:
            await self.connect()
            
            # Check initial state
            initial = await self.get_stats()
            print(f"\n📊 Initial state:")
            print(f"  Download: {initial['documents_download']}")
            print(f"  Chunks: {initial['documents_chunks']}")
            print(f"  Embeddings: {initial['documents_embeddings']}")
            print(f"  Complete: {initial['documents_complete']}")
            print(f"  Milvus: {initial['milvus']}")
            
            if any(v > 0 for k, v in initial.items() if k != 'milvus'):
                print("⚠️ WARNING: Queues not empty, may affect test")
            
            await self.send_document()
            await self.monitor()
            
        finally:
            if self.nc:
                await self.nc.close()
            connections.disconnect("default")
            print("\n✅ Monitoring complete")


if __name__ == "__main__":
    monitor = FlowMonitor()
    asyncio.run(monitor.run())