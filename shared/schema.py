"""
Milvus collection schema definitions and utilities

This module provides comprehensive schema definitions for all Milvus collections
used in the RAG system, along with utilities for schema management and validation.
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from pymilvus import FieldSchema, CollectionSchema, DataType

logger = logging.getLogger(__name__)


@dataclass
class SchemaField:
    """Schema field definition with validation"""
    name: str
    dtype: DataType
    description: str
    max_length: Optional[int] = None
    dim: Optional[int] = None
    is_primary: bool = False
    auto_id: bool = False
    is_partition_key: bool = False
    nullable: bool = False
    
    def to_field_schema(self) -> FieldSchema:
        """Convert to Milvus FieldSchema"""
        kwargs = {
            'name': self.name,
            'dtype': self.dtype,
            'description': self.description
        }
        
        if self.max_length is not None:
            kwargs['max_length'] = self.max_length
        
        if self.dim is not None:
            kwargs['dim'] = self.dim
            
        if self.is_primary:
            kwargs['is_primary'] = True
            kwargs['auto_id'] = self.auto_id
        
        return FieldSchema(**kwargs)


class MedicalDocumentsSchema:
    """
    Schema definition for the medical_documents collection
    
    This schema is optimized for medical document RAG operations with:
    - Fast similarity search using vector embeddings
    - Rich metadata for source attribution
    - Efficient storage and indexing
    """
    
    COLLECTION_NAME = "medical_documents"
    VECTOR_DIMENSION = 768  # text-embedding-004 dimension
    
    # Field definitions
    FIELDS = [
        SchemaField(
            name="chunk_id",
            dtype=DataType.VARCHAR,
            max_length=128,
            is_primary=True,
            auto_id=False,
            description="Unique identifier for document chunk (format: {job_id}_{page}_{chunk})"
        ),
        SchemaField(
            name="embedding",
            dtype=DataType.FLOAT_VECTOR,
            dim=VECTOR_DIMENSION,
            description=f"Text embedding vector ({VECTOR_DIMENSION} dimensions) from Gemini text-embedding-004"
        ),
        SchemaField(
            name="text_content",
            dtype=DataType.VARCHAR,
            max_length=4000,
            description="Document text chunk content (processed by LangChain RecursiveCharacterTextSplitter)"
        ),
        SchemaField(
            name="document_title",
            dtype=DataType.VARCHAR,
            max_length=500,
            description="Title of the source document extracted from PDF metadata or filename"
        ),
        SchemaField(
            name="source_url",
            dtype=DataType.VARCHAR,
            max_length=1000,
            description="Original URL or file path of the source document"
        ),
        SchemaField(
            name="page_number",
            dtype=DataType.INT32,
            description="Page number where this chunk appears in the source document (1-indexed)"
        ),
        SchemaField(
            name="diseases",
            dtype=DataType.VARCHAR,
            max_length=2000,
            description="JSON array of related diseases/conditions mentioned in this chunk"
        ),
        SchemaField(
            name="processed_at",
            dtype=DataType.VARCHAR,
            max_length=50,
            description="ISO timestamp when this chunk was processed and embedded"
        ),
        SchemaField(
            name="job_id",
            dtype=DataType.VARCHAR,
            max_length=100,
            description="Processing job identifier for tracking document processing batches"
        )
    ]
    
    @classmethod
    def get_schema(cls) -> CollectionSchema:
        """
        Get the complete collection schema
        
        Returns:
            CollectionSchema: Configured Milvus collection schema
        """
        field_schemas = [field.to_field_schema() for field in cls.FIELDS]
        
        return CollectionSchema(
            fields=field_schemas,
            description=(
                "Medical documents collection for RAG operations. "
                "Stores document chunks with embeddings for semantic search. "
                "Optimized for sub-100ms similarity queries on medical content."
            ),
            enable_dynamic_field=False,  # Strict schema enforcement
            auto_id=False  # Use custom chunk_id as primary key
        )
    
    @classmethod
    def get_field_names(cls) -> List[str]:
        """Get list of all field names"""
        return [field.name for field in cls.FIELDS]
    
    @classmethod
    def get_vector_field(cls) -> str:
        """Get the name of the vector field"""
        return "embedding"
    
    @classmethod
    def get_primary_field(cls) -> str:
        """Get the name of the primary key field"""
        for field in cls.FIELDS:
            if field.is_primary:
                return field.name
        return "chunk_id"  # fallback
    
    @classmethod
    def validate_data(cls, data: Dict[str, Any]) -> List[str]:
        """
        Validate data against schema requirements
        
        Args:
            data: Data dictionary to validate
            
        Returns:
            List[str]: List of validation errors (empty if valid)
        """
        errors = []
        field_names = {field.name for field in cls.FIELDS}
        
        # Check for missing required fields
        for field in cls.FIELDS:
            if field.name not in data:
                errors.append(f"Missing required field: {field.name}")
        
        # Check for extra fields
        for key in data.keys():
            if key not in field_names:
                errors.append(f"Unknown field: {key}")
        
        # Validate field-specific constraints
        if 'chunk_id' in data:
            if not isinstance(data['chunk_id'], str) or len(data['chunk_id']) > 128:
                errors.append("chunk_id must be a string with max length 128")
        
        if 'embedding' in data:
            if not isinstance(data['embedding'], list):
                errors.append("embedding must be a list")
            elif len(data['embedding']) != cls.VECTOR_DIMENSION:
                errors.append(f"embedding must have exactly {cls.VECTOR_DIMENSION} dimensions")
        
        if 'text_content' in data:
            if not isinstance(data['text_content'], str) or len(data['text_content']) > 4000:
                errors.append("text_content must be a string with max length 4000")
        
        if 'page_number' in data:
            if not isinstance(data['page_number'], int) or data['page_number'] < 1:
                errors.append("page_number must be a positive integer")
        
        return errors


class IndexConfiguration:
    """
    Index configuration for optimal similarity search performance
    
    Configured for medical document RAG with:
    - Sub-100ms query performance
    - COSINE similarity for text embeddings
    - Balanced precision/performance tradeoff
    """
    
    # Index parameters optimized for medical document search
    VECTOR_INDEX_CONFIG = {
        "index_type": "IVF_FLAT",
        "metric_type": "COSINE",
        "params": {
            "nlist": 128  # Reduced from 1024 for better performance on smaller datasets
        }
    }
    
    # Search parameters for query optimization
    SEARCH_PARAMS = {
        "metric_type": "COSINE",
        "params": {
            "nprobe": 16  # Number of clusters to search (balance between speed and accuracy)
        }
    }
    
    @classmethod
    def get_index_config(cls) -> Dict[str, Any]:
        """Get vector index configuration"""
        return cls.VECTOR_INDEX_CONFIG.copy()
    
    @classmethod
    def get_search_params(cls) -> Dict[str, Any]:
        """Get search parameters for queries"""
        return cls.SEARCH_PARAMS.copy()
    
    @classmethod
    def validate_index_params(cls, params: Dict[str, Any]) -> List[str]:
        """
        Validate index parameters
        
        Args:
            params: Index parameters to validate
            
        Returns:
            List[str]: List of validation errors
        """
        errors = []
        
        if "index_type" not in params:
            errors.append("index_type is required")
        elif params["index_type"] not in ["FLAT", "IVF_FLAT", "IVF_SQ8", "IVF_PQ", "HNSW"]:
            errors.append(f"Unsupported index_type: {params['index_type']}")
        
        if "metric_type" not in params:
            errors.append("metric_type is required")
        elif params["metric_type"] not in ["L2", "IP", "COSINE"]:
            errors.append(f"Unsupported metric_type: {params['metric_type']}")
        
        if params.get("index_type") == "IVF_FLAT":
            if "params" not in params or "nlist" not in params["params"]:
                errors.append("nlist parameter is required for IVF_FLAT index")
            else:
                nlist = params["params"]["nlist"]
                if not isinstance(nlist, int) or nlist < 1 or nlist > 65536:
                    errors.append("nlist must be an integer between 1 and 65536")
        
        return errors


class CollectionSettings:
    """
    Collection-level settings for performance optimization
    """
    
    # Collection configuration
    COLLECTION_CONFIG = {
        # Segment settings for optimal performance
        "segment_row_limit": 1000000,  # 1M rows per segment
        
        # Memory management
        "index_building_threshold": 10000,  # Build index after 10K inserts
        
        # Compaction settings
        "auto_compaction": True,
        
        # Loading strategy
        "loading_progress": 100,  # Load entire collection into memory
        
        # Resource limits
        "memory_replica_num": 1,  # Number of memory replicas
    }
    
    @classmethod
    def get_collection_config(cls) -> Dict[str, Any]:
        """Get collection configuration"""
        return cls.COLLECTION_CONFIG.copy()


# Schema registry for future extensibility
SCHEMA_REGISTRY = {
    "medical_documents": MedicalDocumentsSchema,
}


def get_schema(collection_name: str) -> Optional[CollectionSchema]:
    """
    Get schema for a collection by name
    
    Args:
        collection_name: Name of the collection
        
    Returns:
        CollectionSchema: Schema for the collection, or None if not found
    """
    schema_class = SCHEMA_REGISTRY.get(collection_name)
    if schema_class:
        return schema_class.get_schema()
    return None


def validate_collection_data(collection_name: str, data: Dict[str, Any]) -> List[str]:
    """
    Validate data for a specific collection
    
    Args:
        collection_name: Name of the collection
        data: Data to validate
        
    Returns:
        List[str]: List of validation errors
    """
    schema_class = SCHEMA_REGISTRY.get(collection_name)
    if not schema_class:
        return [f"Unknown collection: {collection_name}"]
    
    return schema_class.validate_data(data)