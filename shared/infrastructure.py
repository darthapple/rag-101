"""
Shared infrastructure initialization for RAG-101 services

Provides consistent infrastructure setup and verification for all services:
- NATS JetStream streams and KV buckets
- Milvus collections and indexes
- Health checks and status monitoring
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
import logging

import nats
from nats.js import JetStreamContext
from nats.js.api import StreamConfig, RetentionPolicy, StorageType, KeyValueConfig
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility

from shared.config import get_config
from shared.logging import get_structured_logger

class InfrastructureManager:
    """
    Manages initialization and verification of all infrastructure components.
    Used by both API and worker services for consistent setup.
    """
    
    def __init__(self, config=None, service_name: str = "unknown"):
        """
        Initialize infrastructure manager
        
        Args:
            config: Configuration object (defaults to get_config())
            service_name: Name of the service using this manager
        """
        self.config = config or get_config()
        self.service_name = service_name
        self.logger = get_structured_logger(f"infrastructure.{service_name}", service_name)
        
        # Connection state
        self.nc: Optional[nats.Client] = None
        self.js: Optional[JetStreamContext] = None
        self.sessions_kv = None
        self.milvus_collection: Optional[Collection] = None
        
        # Status tracking
        self.initialization_status = {
            'nats': {'initialized': False, 'error': None},
            'jetstream': {'initialized': False, 'error': None},
            'milvus': {'initialized': False, 'error': None},
            'timestamp': None
        }
        
    async def initialize_all(self, require_all: bool = False) -> bool:
        """
        Initialize all infrastructure components
        
        Args:
            require_all: If True, fail if any component fails. If False, continue with partial initialization.
            
        Returns:
            bool: True if all components initialized successfully, False if any failed
        """
        self.logger.info(
            "Starting infrastructure initialization",
            service_name=self.service_name,
            require_all=require_all
        )
        
        all_success = True
        self.initialization_status['timestamp'] = datetime.now().isoformat()
        
        # 1. Initialize NATS
        try:
            await self.init_nats()
            self.initialization_status['nats']['initialized'] = True
        except Exception as e:
            self.initialization_status['nats']['error'] = str(e)
            self.logger.error(
                "NATS initialization failed",
                error=e,
                service_name=self.service_name
            )
            all_success = False
            if require_all:
                raise
        
        # 2. Initialize Milvus
        try:
            await self.init_milvus()
            self.initialization_status['milvus']['initialized'] = True
        except Exception as e:
            self.initialization_status['milvus']['error'] = str(e)
            self.logger.error(
                "Milvus initialization failed",
                error=e,
                service_name=self.service_name
            )
            all_success = False
            if require_all:
                raise
        
        # Log initialization summary
        self.logger.info(
            "Infrastructure initialization complete",
            service_name=self.service_name,
            all_success=all_success,
            status=self.initialization_status
        )
        
        return all_success
    
    async def init_nats(self):
        """Initialize NATS connection, JetStream, and KV buckets"""
        max_retries = 3
        retry_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                # Connect to NATS
                self.nc = await nats.connect(
                    servers=[self.config.nats_url],
                    max_reconnect_attempts=self.config.max_reconnect_attempts,
                    reconnect_time_wait=self.config.reconnect_time_wait,
                    ping_interval=self.config.ping_interval,
                    max_outstanding_pings=self.config.max_outstanding_pings,
                    error_cb=self._on_nats_error,
                    disconnected_cb=self._on_nats_disconnected,
                    reconnected_cb=self._on_nats_reconnected
                )
                
                self.logger.info(
                    "Connected to NATS",
                    url=self.config.nats_url,
                    service_name=self.service_name,
                    attempt=attempt + 1
                )
                
                # Get JetStream context
                self.js = self.nc.jetstream()
                self.initialization_status['jetstream']['initialized'] = True
                
                # Create/verify streams
                await self.ensure_jetstream_streams()
                
                # Create/verify KV buckets
                await self.ensure_kv_buckets()
                
                return
                
            except Exception as e:
                self.logger.warning(
                    f"NATS connection attempt {attempt + 1} failed",
                    error=e,
                    url=self.config.nats_url,
                    attempt=attempt + 1,
                    max_retries=max_retries
                )
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 1.5  # Exponential backoff
                else:
                    raise
    
    async def ensure_jetstream_streams(self):
        """Create or verify JetStream streams for all message topics"""
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
                # Check if stream exists
                try:
                    info = await self.js.stream_info(stream_def["name"])
                    self.logger.debug(
                        f"Stream '{stream_def['name']}' exists",
                        subjects=info.config.subjects,
                        messages=info.state.messages
                    )
                    
                    # Update if configuration differs
                    if set(info.config.subjects) != set(stream_def["subjects"]):
                        await self._update_stream(stream_def)
                        
                except nats.js.errors.NotFoundError:
                    # Stream doesn't exist, create it
                    await self._create_stream(stream_def)
                    
            except Exception as e:
                self.logger.error(
                    f"Failed to ensure stream {stream_def['name']}",
                    error=e,
                    service_name=self.service_name
                )
                # Continue with other streams
    
    async def _create_stream(self, stream_def: Dict[str, Any]):
        """Create a new JetStream stream"""
        stream_config = StreamConfig(
            name=stream_def["name"],
            subjects=stream_def["subjects"],
            description=stream_def["description"],
            retention=RetentionPolicy.LIMITS,
            storage=StorageType.FILE,
            max_age=self.config.message_ttl,
            max_msgs=10000,
            max_bytes=100 * 1024 * 1024,  # 100MB
            duplicate_window=60
        )
        
        await self.js.add_stream(stream_config)
        self.logger.info(
            f"Created JetStream stream: {stream_def['name']}",
            subjects=stream_def["subjects"],
            service_name=self.service_name
        )
    
    async def _update_stream(self, stream_def: Dict[str, Any]):
        """Update an existing JetStream stream"""
        stream_config = StreamConfig(
            name=stream_def["name"],
            subjects=stream_def["subjects"],
            description=stream_def["description"],
            retention=RetentionPolicy.LIMITS,
            storage=StorageType.FILE,
            max_age=self.config.message_ttl,
            max_msgs=10000,
            max_bytes=100 * 1024 * 1024,
            duplicate_window=60
        )
        
        await self.js.update_stream(stream_config)
        self.logger.info(
            f"Updated stream configuration: {stream_def['name']}",
            subjects=stream_def["subjects"],
            service_name=self.service_name
        )
    
    async def ensure_kv_buckets(self):
        """Create or verify KV buckets for session storage"""
        try:
            # Check if bucket exists
            try:
                self.sessions_kv = await self.js.key_value("sessions")
                status = await self.sessions_kv.status()
                self.logger.debug(
                    "Connected to existing KV bucket: sessions",
                    values=status.values
                )
            except nats.js.errors.BucketNotFoundError:
                # Create sessions KV bucket
                kv_config = KeyValueConfig(
                    bucket="sessions",
                    description="Session storage for RAG-101",
                    ttl=self.config.session_ttl,
                    max_value_size=10240  # 10KB max per session
                )
                
                self.sessions_kv = await self.js.create_key_value(kv_config)
                self.logger.info(
                    f"Created KV bucket: sessions",
                    ttl=self.config.session_ttl,
                    service_name=self.service_name
                )
                
        except Exception as e:
            self.logger.error(
                "Failed to ensure sessions KV bucket",
                error=e,
                service_name=self.service_name
            )
    
    async def init_milvus(self):
        """Initialize Milvus connection and create collection"""
        try:
            # Connect to Milvus with retry logic
            max_retries = 3
            retry_delay = 2.0
            
            for attempt in range(max_retries):
                try:
                    connections.connect(
                        alias=f"{self.service_name}_milvus",
                        host=self.config.milvus_host,
                        port=self.config.milvus_port,
                        timeout=10.0
                    )
                    
                    self.logger.info(
                        "Connected to Milvus",
                        host=self.config.milvus_host,
                        port=self.config.milvus_port,
                        service_name=self.service_name,
                        attempt=attempt + 1
                    )
                    break
                    
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.logger.warning(
                            f"Milvus connection attempt {attempt + 1} failed",
                            error=e,
                            attempt=attempt + 1,
                            max_retries=max_retries
                        )
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 1.5
                    else:
                        raise
            
            # Create or verify collection
            await self.ensure_milvus_collection()
            
        except Exception as e:
            self.logger.error(
                "Failed to initialize Milvus",
                error=e,
                service_name=self.service_name
            )
            raise
    
    async def ensure_milvus_collection(self):
        """Create or verify Milvus collection for medical documents"""
        collection_name = self.config.collection_name
        
        try:
            # Check if collection exists
            if utility.has_collection(collection_name, using=f"{self.service_name}_milvus"):
                self.milvus_collection = Collection(
                    collection_name, 
                    using=f"{self.service_name}_milvus"
                )
                
                # Verify schema matches expected
                if not self._verify_collection_schema(self.milvus_collection):
                    self.logger.warning(
                        "Collection schema mismatch",
                        collection=collection_name,
                        service_name=self.service_name
                    )
                
                # Load collection into memory
                self.milvus_collection.load()
                
                num_entities = self.milvus_collection.num_entities
                self.logger.info(
                    f"Connected to existing collection: {collection_name}",
                    entities=num_entities,
                    service_name=self.service_name
                )
            else:
                # Create new collection
                await self._create_milvus_collection(collection_name)
                
        except Exception as e:
            self.logger.error(
                f"Failed to ensure Milvus collection",
                error=e,
                collection=collection_name,
                service_name=self.service_name
            )
            raise
    
    async def _create_milvus_collection(self, collection_name: str):
        """Create a new Milvus collection with the required schema"""
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
            consistency_level="Strong",
            using=f"{self.service_name}_milvus"
        )
        
        self.logger.info(
            f"Created new collection: {collection_name}",
            fields=len(fields),
            service_name=self.service_name
        )
        
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
        
        self.logger.info(
            "Created vector index",
            index_type="IVF_FLAT",
            metric="COSINE",
            service_name=self.service_name
        )
        
        # Load collection into memory
        self.milvus_collection.load()
        self.logger.info(
            "Loaded collection into memory",
            collection=collection_name,
            service_name=self.service_name
        )
    
    def _verify_collection_schema(self, collection: Collection) -> bool:
        """
        Verify that the collection schema matches our requirements
        
        Args:
            collection: Milvus collection to verify
            
        Returns:
            bool: True if schema matches, False otherwise
        """
        required_fields = {
            'chunk_id', 'embedding', 'text_content', 'document_title',
            'source_url', 'page_number', 'diseases', 'processed_at', 'job_id'
        }
        
        schema = collection.schema
        existing_fields = {field.name for field in schema.fields}
        
        # Check if all required fields exist
        missing_fields = required_fields - existing_fields
        if missing_fields:
            self.logger.warning(
                "Collection missing required fields",
                missing=list(missing_fields),
                existing=list(existing_fields)
            )
            return False
        
        # Verify embedding dimension
        for field in schema.fields:
            if field.name == 'embedding':
                if field.params.get('dim') != self.config.vector_dimension:
                    self.logger.warning(
                        "Embedding dimension mismatch",
                        expected=self.config.vector_dimension,
                        actual=field.params.get('dim')
                    )
                    return False
        
        return True
    
    async def cleanup(self):
        """Cleanup connections on shutdown"""
        try:
            # Close NATS connection
            if self.nc and not self.nc.is_closed:
                await self.nc.close()
                self.logger.info(
                    "NATS connection closed",
                    service_name=self.service_name
                )
            
            # Close Milvus connection
            alias = f"{self.service_name}_milvus"
            if connections.has_connection(alias):
                connections.remove_connection(alias)
                self.logger.info(
                    "Milvus connection closed",
                    service_name=self.service_name
                )
                
        except Exception as e:
            self.logger.error(
                "Error during cleanup",
                error=e,
                service_name=self.service_name
            )
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get infrastructure status
        
        Returns:
            Dict[str, Any]: Status information for all components
        """
        return {
            "service": self.service_name,
            "initialization": self.initialization_status,
            "nats": {
                "connected": self.nc is not None and not self.nc.is_closed,
                "url": self.config.nats_url,
                "jetstream": self.js is not None,
                "sessions_kv": self.sessions_kv is not None
            },
            "milvus": {
                "connected": connections.has_connection(f"{self.service_name}_milvus"),
                "host": f"{self.config.milvus_host}:{self.config.milvus_port}",
                "collection": self.config.collection_name if self.milvus_collection else None,
                "vector_dimension": self.config.vector_dimension,
                "entities": self.milvus_collection.num_entities if self.milvus_collection else 0
            },
            "timestamp": datetime.now().isoformat()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on all infrastructure components
        
        Returns:
            Dict[str, Any]: Health status for each component
        """
        health = {
            "healthy": True,
            "components": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Check NATS
        try:
            if self.nc and not self.nc.is_closed:
                # Try to get server info
                info = await self.nc.server_info()
                health["components"]["nats"] = {
                    "status": "healthy",
                    "server_id": info.get("server_id"),
                    "version": info.get("version")
                }
            else:
                health["components"]["nats"] = {"status": "disconnected"}
                health["healthy"] = False
        except Exception as e:
            health["components"]["nats"] = {"status": "error", "error": str(e)}
            health["healthy"] = False
        
        # Check JetStream
        try:
            if self.js:
                info = await self.js.account_info()
                health["components"]["jetstream"] = {
                    "status": "healthy",
                    "streams": info.streams,
                    "memory": info.memory,
                    "storage": info.storage
                }
            else:
                health["components"]["jetstream"] = {"status": "not_initialized"}
                health["healthy"] = False
        except Exception as e:
            health["components"]["jetstream"] = {"status": "error", "error": str(e)}
            health["healthy"] = False
        
        # Check Milvus
        try:
            alias = f"{self.service_name}_milvus"
            if connections.has_connection(alias):
                # Try to get collection stats
                if self.milvus_collection:
                    health["components"]["milvus"] = {
                        "status": "healthy",
                        "collection": self.config.collection_name,
                        "entities": self.milvus_collection.num_entities
                    }
                else:
                    health["components"]["milvus"] = {"status": "no_collection"}
            else:
                health["components"]["milvus"] = {"status": "disconnected"}
                health["healthy"] = False
        except Exception as e:
            health["components"]["milvus"] = {"status": "error", "error": str(e)}
            health["healthy"] = False
        
        return health
    
    # NATS callbacks
    async def _on_nats_error(self, error):
        """Handle NATS errors"""
        self.logger.error(
            "NATS error callback",
            error=error,
            service_name=self.service_name
        )
    
    async def _on_nats_disconnected(self):
        """Handle NATS disconnection"""
        self.logger.warning(
            "NATS disconnected",
            service_name=self.service_name
        )
    
    async def _on_nats_reconnected(self):
        """Handle NATS reconnection"""
        self.logger.info(
            "NATS reconnected",
            service_name=self.service_name
        )


async def verify_infrastructure(service_name: str = "unknown", require_all: bool = False) -> InfrastructureManager:
    """
    Convenience function to verify infrastructure for a service
    
    Args:
        service_name: Name of the service
        require_all: If True, fail if any component fails
        
    Returns:
        InfrastructureManager: Initialized infrastructure manager
        
    Raises:
        Exception: If require_all=True and any component fails
    """
    manager = InfrastructureManager(service_name=service_name)
    await manager.initialize_all(require_all=require_all)
    return manager