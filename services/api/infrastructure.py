"""
Infrastructure initialization for RAG-101 API
Handles NATS, Milvus, and other service setup
"""

import asyncio
import json
from datetime import datetime
from typing import Optional

import nats
from nats.js import JetStreamContext
from nats.js.api import StreamConfig, RetentionPolicy, StorageType, KeyValueConfig
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility
import logging

logger = logging.getLogger(__name__)

class InfrastructureManager:
    """Manages initialization of all infrastructure components"""
    
    def __init__(self, config):
        self.config = config
        self.nc: Optional[nats.Client] = None
        self.js: Optional[JetStreamContext] = None
        self.sessions_kv = None
        self.milvus_collection: Optional[Collection] = None
        
    async def initialize_all(self):
        """Initialize all infrastructure components"""
        print("=" * 60)
        print("Initializing RAG-101 Infrastructure")
        print("=" * 60)
        
        # 1. Initialize NATS
        await self.init_nats()
        
        # 2. Initialize Milvus
        self.init_milvus()
        
        print("=" * 60)
        print("Infrastructure initialization complete!")
        print("=" * 60)
        
    async def init_nats(self):
        """Initialize NATS connection, JetStream, and KV buckets"""
        try:
            # Connect to NATS
            self.nc = await nats.connect(self.config.nats_url)
            print(f"✓ Connected to NATS at {self.config.nats_url}")
            
            # Get JetStream context
            self.js = self.nc.jetstream()
            
            # Create streams for message topics
            await self.create_jetstream_streams()
            
            # Create KV bucket for sessions
            await self.create_kv_buckets()
            
        except Exception as e:
            print(f"✗ Failed to initialize NATS: {e}")
            raise
    
    async def create_jetstream_streams(self):
        """Create JetStream streams for all message topics"""
        streams = [
            {
                "name": "questions",
                "subjects": ["questions", "questions.>"],
                "description": "Stream for user questions"
            },
            {
                "name": "answers",
                "subjects": ["answers", "answers.>"],
                "description": "Stream for generated answers"
            },
            {
                "name": "documents",
                "subjects": ["documents", "documents.>"],
                "description": "Stream for document processing"
            },
            {
                "name": "embeddings",
                "subjects": ["embeddings", "embeddings.>"],
                "description": "Stream for embedding generation"
            },
            {
                "name": "system",
                "subjects": ["system", "system.>"],
                "description": "Stream for system metrics and events"
            }
        ]
        
        for stream_def in streams:
            try:
                # Try to create the stream
                stream_config = StreamConfig(
                    name=stream_def["name"],
                    subjects=stream_def["subjects"],
                    description=stream_def["description"],
                    retention=RetentionPolicy.LIMITS,
                    storage=StorageType.FILE,
                    max_age=self.config.message_ttl,  # Already in seconds
                    max_msgs=10000,
                    max_bytes=100 * 1024 * 1024,  # 100MB
                    duplicate_window=60  # 60 seconds
                )
                
                await self.js.add_stream(stream_config)
                print(f"  ✓ Created JetStream stream: {stream_def['name']}")
                
            except Exception as e:
                if "already exists" in str(e).lower() or "already in use" in str(e).lower():
                    # Stream already exists, update it
                    try:
                        stream_config = StreamConfig(
                            name=stream_def["name"],
                            subjects=stream_def["subjects"],
                            description=stream_def["description"],
                            retention=RetentionPolicy.LIMITS,
                            storage=StorageType.FILE,
                            max_age=self.config.message_ttl * 1_000_000_000,
                            max_msgs=10000,
                            max_bytes=100 * 1024 * 1024,
                            duplicate_window=60 * 1_000_000_000
                        )
                        await self.js.update_stream(stream_config)
                        print(f"  ✓ Updated existing stream: {stream_def['name']}")
                    except Exception as update_error:
                        print(f"  ⚠ Stream {stream_def['name']} exists (couldn't update: {update_error})")
                else:
                    print(f"  ✗ Failed to create stream {stream_def['name']}: {e}")
    
    async def create_kv_buckets(self):
        """Create KV buckets for session storage"""
        try:
            # Create sessions KV bucket
            kv_config = KeyValueConfig(
                bucket="sessions",
                description="Session storage for RAG-101",
                ttl=self.config.session_ttl,  # Auto-expire sessions
                max_value_size=10240  # 10KB max per session
            )
            
            self.sessions_kv = await self.js.create_key_value(kv_config)
            print(f"  ✓ Created KV bucket: sessions (TTL: {self.config.session_ttl}s)")
            
        except Exception as e:
            if "already" in str(e).lower() or "exists" in str(e).lower():
                # Bucket already exists, get it
                try:
                    self.sessions_kv = await self.js.key_value("sessions")
                    print(f"  ✓ Connected to existing KV bucket: sessions")
                except Exception as get_error:
                    print(f"  ✗ Failed to access sessions KV bucket: {get_error}")
            else:
                print(f"  ✗ Failed to create sessions KV bucket: {e}")
    
    def init_milvus(self):
        """Initialize Milvus connection and create collection"""
        try:
            # Connect to Milvus
            connections.connect(
                alias="default",
                host=self.config.milvus_host,
                port=self.config.milvus_port
            )
            print(f"✓ Connected to Milvus at {self.config.milvus_host}:{self.config.milvus_port}")
            
            # Create collection if it doesn't exist
            self.create_milvus_collection()
            
        except Exception as e:
            print(f"✗ Failed to initialize Milvus: {e}")
            # Don't raise - app can work without Milvus for basic testing
    
    def create_milvus_collection(self):
        """Create or verify Milvus collection for medical documents"""
        collection_name = self.config.collection_name
        
        try:
            # Check if collection exists
            if utility.has_collection(collection_name):
                self.milvus_collection = Collection(collection_name)
                print(f"  ✓ Connected to existing collection: {collection_name}")
                
                # Load collection into memory
                self.milvus_collection.load()
                print(f"    Loaded collection into memory")
                
                # Get collection info
                num_entities = self.milvus_collection.num_entities
                print(f"    Collection has {num_entities} documents")
            else:
                # Define schema for medical documents
                fields = [
                    FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, is_primary=True, max_length=100),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.config.vector_dimension),
                    FieldSchema(name="text_content", dtype=DataType.VARCHAR, max_length=2000),
                    FieldSchema(name="document_title", dtype=DataType.VARCHAR, max_length=500),
                    FieldSchema(name="source_url", dtype=DataType.VARCHAR, max_length=500),
                    FieldSchema(name="page_number", dtype=DataType.INT64),
                    FieldSchema(name="diseases", dtype=DataType.VARCHAR, max_length=500),
                    FieldSchema(name="processed_at", dtype=DataType.INT64),
                    FieldSchema(name="job_id", dtype=DataType.VARCHAR, max_length=100)
                ]
                
                schema = CollectionSchema(
                    fields=fields,
                    description="Medical documents with embeddings for RAG-101"
                )
                
                # Create collection
                self.milvus_collection = Collection(
                    name=collection_name,
                    schema=schema,
                    consistency_level="Strong"
                )
                print(f"  ✓ Created new collection: {collection_name}")
                
                # Create index for similarity search
                index_params = {
                    "metric_type": "COSINE",
                    "index_type": "IVF_FLAT",
                    "params": {"nlist": 128}
                }
                
                self.milvus_collection.create_index(
                    field_name="embedding",
                    index_params=index_params
                )
                print(f"    Created IVF_FLAT index with COSINE similarity")
                
                # Load collection into memory
                self.milvus_collection.load()
                print(f"    Loaded collection into memory")
                
        except Exception as e:
            print(f"  ✗ Failed to create/access Milvus collection: {e}")
    
    async def cleanup(self):
        """Cleanup connections on shutdown"""
        if self.nc:
            await self.nc.close()
            print("✓ NATS connection closed")
        
        if connections.has_connection("default"):
            connections.remove_connection("default")
            print("✓ Milvus connection closed")
    
    def get_status(self):
        """Get infrastructure status"""
        return {
            "nats": {
                "connected": self.nc is not None and not self.nc.is_closed,
                "url": self.config.nats_url,
                "jetstream": self.js is not None,
                "sessions_kv": self.sessions_kv is not None
            },
            "milvus": {
                "connected": connections.has_connection("default"),
                "host": f"{self.config.milvus_host}:{self.config.milvus_port}",
                "collection": self.config.collection_name if self.milvus_collection else None,
                "vector_dimension": self.config.vector_dimension
            }
        }