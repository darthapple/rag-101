import os
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility
from pymilvus.exceptions import MilvusException

logger = logging.getLogger(__name__)


class MilvusConnectionError(Exception):
    """Custom exception for Milvus connection errors"""
    pass


class MilvusOperationError(Exception):
    """Custom exception for Milvus operation errors"""
    pass


class MilvusDatabase:
    """
    Milvus database client for RAG operations
    
    Handles connection management, collection operations, and vector search
    for the medical documents collection.
    """
    
    def __init__(self, 
                 host: str = None,
                 port: int = None,
                 alias: str = "default",
                 timeout: float = 30.0):
        """
        Initialize Milvus database client
        
        Args:
            host: Milvus server host (default from env MILVUS_HOST)
            port: Milvus server port (default from env MILVUS_PORT) 
            alias: Connection alias name
            timeout: Connection timeout in seconds
        """
        self.host = host or os.getenv('MILVUS_HOST', 'localhost')
        self.port = port or int(os.getenv('MILVUS_PORT', '19530'))
        self.alias = alias
        self.timeout = timeout
        self.collection_name = 'medical_documents'
        self._collection = None
        self._connected = False
        
        # Collection schema configuration
        self.vector_dimension = int(os.getenv('VECTOR_DIMENSION', '768'))
        self.index_type = 'IVF_FLAT'
        self.metric_type = 'COSINE'
        
    def connect(self) -> bool:
        """
        Establish connection to Milvus server with retry logic
        
        Returns:
            bool: True if connection successful
            
        Raises:
            MilvusConnectionError: If connection fails after retries
        """
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # Check if already connected
                if self._connected and self.alias in connections.list_connections():
                    logger.info(f"Already connected to Milvus at {self.host}:{self.port}")
                    return True
                
                # Establish new connection
                connections.connect(
                    alias=self.alias,
                    host=self.host,
                    port=self.port,
                    timeout=self.timeout
                )
                
                # Verify connection
                if not connections.has_connection(self.alias):
                    raise MilvusConnectionError(f"Failed to establish connection with alias {self.alias}")
                
                self._connected = True
                logger.info(f"Successfully connected to Milvus at {self.host}:{self.port}")
                return True
                
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise MilvusConnectionError(f"Failed to connect after {max_retries} attempts: {str(e)}")
    
    def disconnect(self):
        """Disconnect from Milvus server"""
        try:
            if self._connected and self.alias in connections.list_connections():
                connections.disconnect(self.alias)
                self._connected = False
                logger.info("Disconnected from Milvus")
        except Exception as e:
            logger.error(f"Error during disconnect: {str(e)}")
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check Milvus connection and server health
        
        Returns:
            dict: Health check results with status and details
        """
        try:
            # Check connection
            if not self._connected:
                self.connect()
            
            # Get server version
            version = utility.get_server_version(using=self.alias)
            
            # Check if collection exists and get stats
            collection_exists = utility.has_collection(self.collection_name, using=self.alias)
            collection_stats = None
            
            if collection_exists:
                collection = Collection(self.collection_name, using=self.alias)
                collection_stats = {
                    'num_entities': collection.num_entities,
                    'is_empty': collection.is_empty
                }
            
            return {
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'server_version': version,
                'connection': {
                    'host': self.host,
                    'port': self.port,
                    'alias': self.alias,
                    'connected': self._connected
                },
                'collection': {
                    'name': self.collection_name,
                    'exists': collection_exists,
                    'stats': collection_stats
                }
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return {
                'status': 'unhealthy',
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }
    
    def _create_collection_schema(self) -> CollectionSchema:
        """
        Create collection schema for medical_documents
        
        Schema includes:
        - chunk_id: Primary key (string)
        - embedding: 768-dimensional vector
        - text_content: Document text chunk
        - document_title: Document title
        - source_url: Source document URL
        - page_number: Page number in document
        - diseases: Related diseases (JSON string)
        - processed_at: Processing timestamp
        - job_id: Processing job ID
        
        Returns:
            CollectionSchema: Configured collection schema
        """
        fields = [
            FieldSchema(
                name="chunk_id",
                dtype=DataType.VARCHAR,
                max_length=128,
                is_primary=True,
                description="Unique identifier for document chunk"
            ),
            FieldSchema(
                name="embedding", 
                dtype=DataType.FLOAT_VECTOR,
                dim=self.vector_dimension,
                description=f"Text embedding vector ({self.vector_dimension}D)"
            ),
            FieldSchema(
                name="text_content",
                dtype=DataType.VARCHAR,
                max_length=4000,
                description="Document text chunk content"
            ),
            FieldSchema(
                name="document_title",
                dtype=DataType.VARCHAR,
                max_length=500,
                description="Title of source document"
            ),
            FieldSchema(
                name="source_url",
                dtype=DataType.VARCHAR,
                max_length=1000,
                description="URL of source document"
            ),
            FieldSchema(
                name="page_number",
                dtype=DataType.INT32,
                description="Page number in source document"
            ),
            FieldSchema(
                name="diseases",
                dtype=DataType.VARCHAR,
                max_length=2000,
                description="Related diseases (JSON array)"
            ),
            FieldSchema(
                name="processed_at",
                dtype=DataType.VARCHAR,
                max_length=50,
                description="Processing timestamp (ISO format)"
            ),
            FieldSchema(
                name="job_id",
                dtype=DataType.VARCHAR,
                max_length=100,
                description="Processing job identifier"
            )
        ]
        
        schema = CollectionSchema(
            fields=fields,
            description="Medical documents collection for RAG operations",
            enable_dynamic_field=False
        )
        
        return schema
    
    def _create_index_params(self) -> Dict[str, Any]:
        """
        Create index parameters for vector field
        
        Returns:
            dict: Index configuration parameters
        """
        return {
            "index_type": self.index_type,
            "metric_type": self.metric_type,
            "params": {
                "nlist": 1024  # Number of cluster units
            }
        }
    
    def create_collection(self) -> bool:
        """
        Create the medical_documents collection if it doesn't exist
        
        Returns:
            bool: True if collection created or already exists
            
        Raises:
            MilvusOperationError: If collection creation fails
        """
        try:
            if not self._connected:
                self.connect()
            
            # Check if collection already exists
            if utility.has_collection(self.collection_name, using=self.alias):
                logger.info(f"Collection '{self.collection_name}' already exists")
                self._collection = Collection(self.collection_name, using=self.alias)
                return True
            
            # Create collection with schema
            schema = self._create_collection_schema()
            collection = Collection(
                name=self.collection_name,
                schema=schema,
                using=self.alias
            )
            
            logger.info(f"Created collection '{self.collection_name}' with {len(schema.fields)} fields")
            
            # Create index on vector field
            index_params = self._create_index_params()
            collection.create_index(
                field_name="embedding",
                index_params=index_params
            )
            
            logger.info(f"Created index on 'embedding' field with {self.index_type}/{self.metric_type}")
            
            # Load collection into memory
            collection.load()
            logger.info(f"Loaded collection '{self.collection_name}' into memory")
            
            self._collection = collection
            return True
            
        except Exception as e:
            logger.error(f"Failed to create collection: {str(e)}")
            raise MilvusOperationError(f"Collection creation failed: {str(e)}")
    
    def drop_collection(self) -> bool:
        """
        Drop the medical_documents collection
        
        Returns:
            bool: True if collection dropped successfully
            
        Raises:
            MilvusOperationError: If collection deletion fails
        """
        try:
            if not self._connected:
                self.connect()
            
            if not utility.has_collection(self.collection_name, using=self.alias):
                logger.warning(f"Collection '{self.collection_name}' does not exist")
                return True
            
            # Release collection from memory first
            collection = Collection(self.collection_name, using=self.alias)
            collection.release()
            
            # Drop collection
            utility.drop_collection(self.collection_name, using=self.alias)
            logger.info(f"Dropped collection '{self.collection_name}'")
            
            self._collection = None
            return True
            
        except Exception as e:
            logger.error(f"Failed to drop collection: {str(e)}")
            raise MilvusOperationError(f"Collection deletion failed: {str(e)}")
    
    def collection_exists(self) -> bool:
        """
        Check if the medical_documents collection exists
        
        Returns:
            bool: True if collection exists
        """
        try:
            if not self._connected:
                self.connect()
            
            return utility.has_collection(self.collection_name, using=self.alias)
            
        except Exception as e:
            logger.error(f"Failed to check collection existence: {str(e)}")
            return False
    
    def get_collection_info(self) -> Dict[str, Any]:
        """
        Get detailed information about the collection
        
        Returns:
            dict: Collection information and statistics
        """
        try:
            if not self._connected:
                self.connect()
            
            if not utility.has_collection(self.collection_name, using=self.alias):
                return {
                    'exists': False,
                    'error': f"Collection '{self.collection_name}' does not exist"
                }
            
            collection = Collection(self.collection_name, using=self.alias)
            
            # Get collection statistics
            collection.load()  # Ensure collection is loaded
            
            return {
                'exists': True,
                'name': self.collection_name,
                'description': collection.description,
                'num_entities': collection.num_entities,
                'is_empty': collection.is_empty,
                'schema': {
                    'fields': [
                        {
                            'name': field.name,
                            'type': str(field.dtype),
                            'is_primary': field.is_primary,
                            'description': field.description
                        }
                        for field in collection.schema.fields
                    ],
                    'enable_dynamic_field': collection.schema.enable_dynamic_field
                },
                'indexes': [
                    {
                        'field_name': idx.field_name,
                        'index_name': idx.index_name,
                        'params': idx.params
                    }
                    for idx in collection.indexes
                ]
            }
            
        except Exception as e:
            logger.error(f"Failed to get collection info: {str(e)}")
            return {
                'exists': False,
                'error': str(e)
            }
    
    def get_collection(self) -> Collection:
        """
        Get the collection instance, creating it if necessary
        
        Returns:
            Collection: Milvus collection instance
            
        Raises:
            MilvusOperationError: If collection access fails
        """
        try:
            if not self._connected:
                self.connect()
            
            if not self.collection_exists():
                self.create_collection()
            
            if self._collection is None:
                self._collection = Collection(self.collection_name, using=self.alias)
            
            return self._collection
            
        except Exception as e:
            logger.error(f"Failed to get collection: {str(e)}")
            raise MilvusOperationError(f"Collection access failed: {str(e)}")
    
    def similarity_search(self, 
                         query_vector: List[float], 
                         top_k: int = 10,
                         filters: Optional[str] = None,
                         output_fields: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Perform similarity search on the collection
        
        Args:
            query_vector: Query embedding vector
            top_k: Number of top results to return
            filters: Optional filter expression
            output_fields: Fields to include in results
            
        Returns:
            list: Search results with scores and metadata
            
        Raises:
            MilvusOperationError: If search fails
        """
        try:
            collection = self.get_collection()
            
            # Default output fields
            if output_fields is None:
                output_fields = [
                    "chunk_id", "text_content", "document_title", 
                    "source_url", "page_number", "diseases", 
                    "processed_at", "job_id"
                ]
            
            # Search parameters
            search_params = {
                "metric_type": self.metric_type,
                "params": {
                    "nprobe": min(16, top_k)  # Number of clusters to search
                }
            }
            
            # Perform search
            results = collection.search(
                data=[query_vector],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=filters,
                output_fields=output_fields
            )
            
            # Format results
            formatted_results = []
            for hits in results:
                for hit in hits:
                    result = {
                        'id': hit.id,
                        'score': hit.score,
                        'distance': hit.distance
                    }
                    # Add output fields
                    for field in output_fields:
                        if hasattr(hit.entity, field):
                            result[field] = getattr(hit.entity, field)
                    
                    formatted_results.append(result)
            
            logger.info(f"Found {len(formatted_results)} similar documents")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Similarity search failed: {str(e)}")
            raise MilvusOperationError(f"Search operation failed: {str(e)}")
    
    def batch_insert(self, data: List[Dict[str, Any]]) -> List[str]:
        """
        Insert multiple documents into the collection
        
        Args:
            data: List of documents to insert
            
        Returns:
            list: List of inserted chunk IDs
            
        Raises:
            MilvusOperationError: If insertion fails
        """
        try:
            if not data:
                logger.warning("No data provided for insertion")
                return []
            
            collection = self.get_collection()
            
            # Prepare data for insertion
            entities = [
                [doc.get("chunk_id") for doc in data],
                [doc.get("embedding") for doc in data],
                [doc.get("text_content") for doc in data],
                [doc.get("document_title") for doc in data],
                [doc.get("source_url") for doc in data],
                [doc.get("page_number") for doc in data],
                [doc.get("diseases") for doc in data],
                [doc.get("processed_at") for doc in data],
                [doc.get("job_id") for doc in data]
            ]
            
            # Insert data
            insert_result = collection.insert(entities)
            
            # Flush to ensure data is persisted
            collection.flush()
            
            logger.info(f"Inserted {len(data)} documents into collection")
            return insert_result.primary_keys
            
        except Exception as e:
            logger.error(f"Batch insert failed: {str(e)}")
            raise MilvusOperationError(f"Insert operation failed: {str(e)}")
    
    def get_by_id(self, chunk_ids: List[str], 
                  output_fields: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Retrieve documents by chunk IDs
        
        Args:
            chunk_ids: List of chunk IDs to retrieve
            output_fields: Fields to include in results
            
        Returns:
            list: Retrieved documents
            
        Raises:
            MilvusOperationError: If retrieval fails
        """
        try:
            if not chunk_ids:
                return []
            
            collection = self.get_collection()
            
            # Default output fields
            if output_fields is None:
                output_fields = [
                    "chunk_id", "text_content", "document_title",
                    "source_url", "page_number", "diseases",
                    "processed_at", "job_id"
                ]
            
            # Query by primary keys
            results = collection.query(
                expr=f"chunk_id in {chunk_ids}",
                output_fields=output_fields
            )
            
            logger.info(f"Retrieved {len(results)} documents by ID")
            return results
            
        except Exception as e:
            logger.error(f"Get by ID failed: {str(e)}")
            raise MilvusOperationError(f"Retrieval operation failed: {str(e)}")
    
    def delete_by_filter(self, filter_expr: str) -> int:
        """
        Delete documents matching a filter expression
        
        Args:
            filter_expr: Milvus filter expression
            
        Returns:
            int: Number of deleted documents
            
        Raises:
            MilvusOperationError: If deletion fails
        """
        try:
            collection = self.get_collection()
            
            # Delete entities matching filter
            delete_result = collection.delete(filter_expr)
            
            # Flush to ensure deletion is persisted
            collection.flush()
            
            deleted_count = delete_result.delete_count if hasattr(delete_result, 'delete_count') else 0
            logger.info(f"Deleted {deleted_count} documents matching filter: {filter_expr}")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Delete by filter failed: {str(e)}")
            raise MilvusOperationError(f"Delete operation failed: {str(e)}")
    
    def delete_by_ids(self, chunk_ids: List[str]) -> int:
        """
        Delete documents by chunk IDs
        
        Args:
            chunk_ids: List of chunk IDs to delete
            
        Returns:
            int: Number of deleted documents
        """
        if not chunk_ids:
            return 0
        
        # Create filter expression for chunk IDs
        filter_expr = f"chunk_id in {chunk_ids}"
        return self.delete_by_filter(filter_expr)
    
    def count_documents(self, filter_expr: Optional[str] = None) -> int:
        """
        Count documents in the collection
        
        Args:
            filter_expr: Optional filter expression
            
        Returns:
            int: Number of documents
        """
        try:
            collection = self.get_collection()
            
            if filter_expr:
                # Count with filter
                results = collection.query(
                    expr=filter_expr,
                    output_fields=["count(*)"]
                )
                return len(results)
            else:
                # Count all entities
                return collection.num_entities
                
        except Exception as e:
            logger.error(f"Count documents failed: {str(e)}")
            return 0
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
    
    def reset_connection(self):
        """Reset and reconnect to Milvus"""
        logger.info("Resetting Milvus connection")
        self.disconnect()
        time.sleep(1)
        self.connect()


# Utility functions for easy database access
def create_database(host: str = None, port: int = None) -> MilvusDatabase:
    """
    Create a MilvusDatabase instance with default configuration
    
    Args:
        host: Milvus server host
        port: Milvus server port
        
    Returns:
        MilvusDatabase: Configured database instance
    """
    return MilvusDatabase(host=host, port=port)


def get_database() -> MilvusDatabase:
    """
    Get a singleton MilvusDatabase instance
    
    Returns:
        MilvusDatabase: Database instance
    """
    if not hasattr(get_database, '_instance'):
        get_database._instance = MilvusDatabase()
    
    return get_database._instance