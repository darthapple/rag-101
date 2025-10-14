#!/usr/bin/env python3
"""
Test Document Flow Script
Tests the complete document processing pipeline from download to Milvus storage.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Dict, Any

import nats
import nats.js.api
from nats.js import JetStreamContext
from pymilvus import connections, Collection, utility


class DocumentFlowTester:
    def __init__(self):
        self.nc = None
        self.js = None
        self.test_url = "https://www.gov.br/saude/pt-br/assuntos/pcdt/a/artrite-reumatoide-e-artrite-idiopatica-juvenil-portaria-conjunta-no-16/@@download/file"
        self.job_id = str(uuid.uuid4())
        self.session_id = "test-session-" + str(uuid.uuid4())
        
    async def connect(self):
        """Connect to NATS and Milvus"""
        # Connect to NATS - use container name when running inside Docker
        self.nc = await nats.connect("nats://nats:4222")
        self.js = self.nc.jetstream()
        print("✅ Connected to NATS")
        
        # Connect to Milvus - use container name when running inside Docker
        connections.connect("default", host='standalone', port='19530')
        print("✅ Connected to Milvus")
        
    async def clear_all_data(self):
        """Clear all data from NATS and Milvus"""
        print("\n📋 Phase 1: Clearing all data...")
        
        # Clear NATS streams
        streams_to_clear = [
            "documents_download",
            "documents_chunks", 
            "documents_embeddings",
            "documents_complete"
        ]
        
        for stream_name in streams_to_clear:
            try:
                await self.js.delete_stream(stream_name)
                print(f"  ✅ Deleted stream: {stream_name}")
            except:
                print(f"  ⚠️ Stream {stream_name} doesn't exist or already deleted")
                
            # Recreate stream
            try:
                config = nats.js.api.StreamConfig(
                    name=stream_name,
                    subjects=[stream_name.replace("_", ".")],
                    retention=nats.js.api.RetentionPolicy.WORK_QUEUE,
                    max_age=3600  # 1 hour in seconds
                )
                await self.js.add_stream(config)
                print(f"  ✅ Recreated stream: {stream_name}")
            except Exception as e:
                print(f"  ❌ Error recreating stream {stream_name}: {e}")
        
        # Clear Milvus collection
        if utility.has_collection("medical_documents"):
            collection = Collection("medical_documents")
            # Get current count
            old_count = collection.num_entities
            print(f"  📊 Current Milvus documents: {old_count}")
            
            # Drop collection
            collection.drop()
            print(f"  ✅ Dropped Milvus collection")
            
            # Recreate will be handled by worker on startup
        else:
            print(f"  ℹ️ Milvus collection doesn't exist")
            
        print("  ✅ All data cleared!")
        
    async def get_stream_stats(self):
        """Get current message counts from all streams"""
        stats = {}
        streams = [
            "documents_download",
            "documents_chunks",
            "documents_embeddings", 
            "documents_complete"
        ]
        
        for stream_name in streams:
            try:
                info = await self.js.stream_info(stream_name)
                stats[stream_name] = info.state.messages
            except:
                stats[stream_name] = 0
                
        # Get Milvus count
        if utility.has_collection("medical_documents"):
            collection = Collection("medical_documents")
            stats["milvus"] = collection.num_entities
        else:
            stats["milvus"] = 0
            
        return stats
    
    async def send_document_to_download(self):
        """Send document URL to download queue"""
        print(f"\n📋 Phase 2: Sending document to download queue...")
        print(f"  📄 URL: {self.test_url}")
        print(f"  🆔 Job ID: {self.job_id}")
        
        message = {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "url": self.test_url,
            "timestamp": datetime.now().isoformat(),
            "metadata": {
                "source": "test_script",
                "test_run": True
            }
        }
        
        # Publish to download queue
        ack = await self.js.publish(
            "documents.download",
            json.dumps(message).encode()
        )
        print(f"  ✅ Message sent (sequence: {ack.seq})")
        
        # Check stats
        stats = await self.get_stream_stats()
        print(f"  📊 Queue stats after send:")
        print(f"     download: {stats['documents_download']}")
        print(f"     chunks: {stats['documents_chunks']}")
        print(f"     embeddings: {stats['documents_embeddings']}")
        print(f"     complete: {stats['documents_complete']}")
        print(f"     milvus: {stats['milvus']}")
        
    async def monitor_processing(self):
        """Monitor the processing pipeline"""
        print(f"\n📋 Phase 3: Monitoring document processing...")
        
        start_time = time.time()
        last_stats = None
        no_change_count = 0
        max_wait_time = 300  # 5 minutes max
        
        while True:
            await asyncio.sleep(2)
            
            stats = await self.get_stream_stats()
            elapsed = time.time() - start_time
            
            # Check if stats changed
            if stats != last_stats:
                print(f"\n  ⏱️ [{elapsed:.1f}s] Queue status:")
                print(f"     download: {stats['documents_download']}")
                print(f"     chunks: {stats['documents_chunks']}")
                print(f"     embeddings: {stats['documents_embeddings']}")
                print(f"     complete: {stats['documents_complete']}")
                print(f"     milvus: {stats['milvus']}")
                
                last_stats = stats
                no_change_count = 0
            else:
                no_change_count += 1
                
            # Check if processing is complete
            if (stats['documents_download'] == 0 and 
                stats['documents_chunks'] == 0 and
                stats['documents_embeddings'] == 0 and
                stats['documents_complete'] == 0 and
                stats['milvus'] > 0):
                
                print(f"\n✅ Processing complete!")
                print(f"  📊 Final stats:")
                print(f"     Total documents in Milvus: {stats['milvus']}")
                print(f"     Processing time: {elapsed:.1f} seconds")
                
                if stats['milvus'] == 706:
                    print("  🎉 SUCCESS: All 706 chunks stored correctly!")
                else:
                    print(f"  ⚠️ WARNING: Expected 706 chunks, got {stats['milvus']}")
                    
                break
                
            # Timeout check
            if elapsed > max_wait_time:
                print(f"\n❌ Timeout after {elapsed:.1f} seconds")
                print(f"  📊 Final queue state:")
                for key, value in stats.items():
                    if value > 0:
                        print(f"     {key}: {value} (STUCK)")
                break
                
            # Stuck detection
            if no_change_count > 30:  # No change for 60 seconds
                print(f"\n⚠️ Processing appears stuck (no change for 60s)")
                print(f"  📊 Current state:")
                for key, value in stats.items():
                    if value > 0:
                        print(f"     {key}: {value}")
                        
    async def check_worker_logs(self):
        """Check for errors in worker logs"""
        print(f"\n📋 Checking worker logs for errors...")
        # This would need Docker API access to get logs
        # For now, just remind user to check manually
        print("  ℹ️ Run 'docker logs rag-101-worker --tail 50' to check for errors")
        
    async def run_test(self):
        """Run the complete test flow"""
        print("🚀 Starting Document Flow Test")
        print("=" * 50)
        
        try:
            await self.connect()
            await self.clear_all_data()
            
            # Give worker time to reconnect after stream recreation
            print("\n⏳ Waiting 5s for worker to reconnect...")
            await asyncio.sleep(5)
            
            await self.send_document_to_download()
            await self.monitor_processing()
            await self.check_worker_logs()
            
        except Exception as e:
            print(f"\n❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            if self.nc:
                await self.nc.close()
            connections.disconnect("default")
            print("\n✅ Test complete!")


if __name__ == "__main__":
    tester = DocumentFlowTester()
    asyncio.run(tester.run_test())