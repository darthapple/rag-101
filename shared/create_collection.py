"""
Collection creation script for Milvus vector database

This script provides functionality to create and initialize the medical_documents
collection using the schema and configuration defined in shared/schema.py.
"""

import logging
import sys
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from shared.database import MilvusDatabase, MilvusConnectionError, MilvusOperationError
from shared.schema import MedicalDocumentsSchema, IndexConfiguration, CollectionSettings
from shared.config import get_config

logger = logging.getLogger(__name__)


class CollectionCreator:
    """
    Collection creation and management utility
    
    Provides methods for creating, validating, and managing the medical_documents
    collection with proper schema, indexing, and optimization settings.
    """
    
    def __init__(self, db: Optional[MilvusDatabase] = None):
        """
        Initialize collection creator
        
        Args:
            db: Optional MilvusDatabase instance. If not provided, will create one from config.
        """
        self.config = get_config()
        self.db = db or MilvusDatabase(
            host=self.config.milvus_host,
            port=self.config.milvus_port,
            alias=self.config.milvus_alias,
            timeout=self.config.connection_timeout
        )
        self.schema_class = MedicalDocumentsSchema
        self.index_config = IndexConfiguration
        self.collection_settings = CollectionSettings
        
    def connect(self) -> bool:
        """
        Establish connection to Milvus
        
        Returns:
            bool: True if connection successful
            
        Raises:
            MilvusConnectionError: If connection fails
        """
        try:
            return self.db.connect()
        except Exception as e:
            logger.error(f"Failed to connect to Milvus: {e}")
            raise MilvusConnectionError(f"Connection failed: {e}")
    
    def check_collection_exists(self) -> bool:
        """
        Check if the medical_documents collection already exists
        
        Returns:
            bool: True if collection exists
        """
        try:
            return self.db.collection_exists()
        except Exception as e:
            logger.error(f"Error checking collection existence: {e}")
            return False
    
    def validate_schema(self) -> Dict[str, Any]:
        """
        Validate the collection schema configuration
        
        Returns:
            Dict[str, Any]: Validation results with errors if any
        """
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        try:
            # Get schema from schema class
            schema = self.schema_class.get_schema()
            
            # Validate field count
            if len(schema.fields) == 0:
                validation_result['errors'].append("Schema has no fields defined")
                validation_result['valid'] = False
            
            # Validate required fields
            field_names = [field.name for field in schema.fields]
            required_fields = ['chunk_id', 'embedding', 'text_content']
            
            for required_field in required_fields:
                if required_field not in field_names:
                    validation_result['errors'].append(f"Missing required field: {required_field}")
                    validation_result['valid'] = False
            
            # Validate vector field
            vector_field = None
            primary_field = None
            
            for field in schema.fields:
                if field.dtype.name == 'FLOAT_VECTOR':
                    vector_field = field
                if field.is_primary:
                    primary_field = field
            
            if not vector_field:
                validation_result['errors'].append("No vector field found in schema")
                validation_result['valid'] = False
            elif vector_field.dim != self.schema_class.VECTOR_DIMENSION:
                validation_result['errors'].append(
                    f"Vector dimension mismatch: expected {self.schema_class.VECTOR_DIMENSION}, "
                    f"got {vector_field.dim}"
                )
                validation_result['valid'] = False
            
            if not primary_field:
                validation_result['errors'].append("No primary key field found in schema")
                validation_result['valid'] = False
            
            # Validate index configuration
            index_errors = self.index_config.validate_index_params(
                self.index_config.get_index_config()
            )
            validation_result['errors'].extend(index_errors)
            if index_errors:
                validation_result['valid'] = False
            
            logger.info(f"Schema validation completed: {'PASSED' if validation_result['valid'] else 'FAILED'}")
            
        except Exception as e:
            validation_result['errors'].append(f"Schema validation error: {str(e)}")
            validation_result['valid'] = False
            logger.error(f"Schema validation failed: {e}")
        
        return validation_result
    
    def create_collection(self, force: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        """
        Create the medical_documents collection with schema and index
        
        Args:
            force: If True, drop existing collection before creating new one
            dry_run: If True, validate only without creating collection
            
        Returns:
            Dict[str, Any]: Creation result with status and details
        """
        result = {
            'success': False,
            'collection_created': False,
            'index_created': False,
            'collection_loaded': False,
            'message': '',
            'errors': [],
            'details': {}
        }
        
        try:
            # Validate schema first
            logger.info("Validating collection schema...")
            validation = self.validate_schema()
            
            if not validation['valid']:
                result['errors'].extend(validation['errors'])
                result['message'] = "Schema validation failed"
                return result
            
            if dry_run:
                result['success'] = True
                result['message'] = "Dry run completed - schema validation passed"
                return result
            
            # Connect to Milvus
            logger.info("Connecting to Milvus...")
            self.connect()
            
            # Check if collection exists
            collection_exists = self.check_collection_exists()
            
            if collection_exists:
                if not force:
                    result['message'] = f"Collection '{self.schema_class.COLLECTION_NAME}' already exists"
                    logger.info(result['message'])
                    return result
                else:
                    logger.info(f"Dropping existing collection '{self.schema_class.COLLECTION_NAME}'...")
                    self.db.drop_collection()
                    result['details']['dropped_existing'] = True
            
            # Create collection with schema
            logger.info(f"Creating collection '{self.schema_class.COLLECTION_NAME}'...")
            
            from pymilvus import Collection
            
            schema = self.schema_class.get_schema()
            collection = Collection(
                name=self.schema_class.COLLECTION_NAME,
                schema=schema,
                using=self.db.alias
            )
            
            result['collection_created'] = True
            result['details']['collection_name'] = self.schema_class.COLLECTION_NAME
            result['details']['field_count'] = len(schema.fields)
            logger.info(f"Collection created with {len(schema.fields)} fields")
            
            # Create vector index
            logger.info("Creating vector index...")
            index_config = self.index_config.get_index_config()
            
            collection.create_index(
                field_name=self.schema_class.get_vector_field(),
                index_params=index_config
            )
            
            result['index_created'] = True
            result['details']['index_type'] = index_config['index_type']
            result['details']['metric_type'] = index_config['metric_type']
            logger.info(f"Vector index created: {index_config['index_type']} with {index_config['metric_type']}")
            
            # Load collection into memory
            logger.info("Loading collection into memory...")
            collection.load()
            
            result['collection_loaded'] = True
            logger.info("Collection loaded successfully")
            
            # Get final collection info
            self.db._collection = collection
            collection_info = self.db.get_collection_info()
            result['details']['collection_info'] = collection_info
            
            result['success'] = True
            result['message'] = f"Collection '{self.schema_class.COLLECTION_NAME}' created and ready"
            
        except MilvusConnectionError as e:
            error_msg = f"Connection error: {str(e)}"
            result['errors'].append(error_msg)
            result['message'] = error_msg
            logger.error(error_msg)
            
        except MilvusOperationError as e:
            error_msg = f"Operation error: {str(e)}"
            result['errors'].append(error_msg)
            result['message'] = error_msg
            logger.error(error_msg)
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            result['errors'].append(error_msg)
            result['message'] = error_msg
            logger.error(f"Collection creation failed: {e}", exc_info=True)
        
        return result
    
    def get_collection_status(self) -> Dict[str, Any]:
        """
        Get detailed status of the collection
        
        Returns:
            Dict[str, Any]: Collection status information
        """
        try:
            self.connect()
            
            if not self.check_collection_exists():
                return {
                    'exists': False,
                    'message': f"Collection '{self.schema_class.COLLECTION_NAME}' does not exist"
                }
            
            # Get collection info from database
            collection_info = self.db.get_collection_info()
            
            # Add schema validation status
            validation = self.validate_schema()
            collection_info['schema_valid'] = validation['valid']
            collection_info['schema_errors'] = validation['errors']
            
            # Add configuration details
            collection_info['configuration'] = {
                'vector_dimension': self.schema_class.VECTOR_DIMENSION,
                'index_config': self.index_config.get_index_config(),
                'search_params': self.index_config.get_search_params(),
                'collection_settings': self.collection_settings.get_collection_config()
            }
            
            return collection_info
            
        except Exception as e:
            logger.error(f"Failed to get collection status: {e}")
            return {
                'exists': False,
                'error': str(e)
            }
    
    def reset_collection(self) -> Dict[str, Any]:
        """
        Reset collection by dropping and recreating it
        
        Returns:
            Dict[str, Any]: Reset operation result
        """
        logger.info(f"Resetting collection '{self.schema_class.COLLECTION_NAME}'...")
        return self.create_collection(force=True)
    
    def optimize_collection(self) -> Dict[str, Any]:
        """
        Apply optimization settings to existing collection
        
        Returns:
            Dict[str, Any]: Optimization result
        """
        result = {
            'success': False,
            'optimizations_applied': [],
            'message': '',
            'errors': []
        }
        
        try:
            self.connect()
            
            if not self.check_collection_exists():
                result['message'] = f"Collection '{self.schema_class.COLLECTION_NAME}' does not exist"
                return result
            
            from pymilvus import Collection
            collection = Collection(self.schema_class.COLLECTION_NAME, using=self.db.alias)
            
            # Apply collection settings
            settings = self.collection_settings.get_collection_config()
            
            # Note: Many collection settings in Milvus are applied at creation time
            # For existing collections, we can mainly optimize the index and loading
            
            # Ensure collection is loaded
            if not collection.has_index():
                logger.warning("Collection has no index - this may affect performance")
            
            # Load collection with full progress
            collection.load(replica_number=settings.get('memory_replica_num', 1))
            result['optimizations_applied'].append('Collection loaded with replica configuration')
            
            result['success'] = True
            result['message'] = "Collection optimization completed"
            logger.info("Collection optimization applied successfully")
            
        except Exception as e:
            error_msg = f"Optimization failed: {str(e)}"
            result['errors'].append(error_msg)
            result['message'] = error_msg
            logger.error(error_msg)
        
        return result


# CLI Interface Functions

def main():
    """Main CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Milvus collection creation and management utility"
    )
    parser.add_argument(
        "action",
        choices=['create', 'status', 'reset', 'validate', 'optimize'],
        help="Action to perform"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force recreate collection if it exists"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate schema without creating collection"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create collection creator
    creator = CollectionCreator()
    
    try:
        if args.action == 'create':
            print("Creating Milvus collection...")
            result = creator.create_collection(force=args.force, dry_run=args.dry_run)
            
        elif args.action == 'status':
            print("Getting collection status...")
            result = creator.get_collection_status()
            
        elif args.action == 'reset':
            print("Resetting collection...")
            result = creator.reset_collection()
            
        elif args.action == 'validate':
            print("Validating collection schema...")
            result = creator.validate_schema()
            
        elif args.action == 'optimize':
            print("Optimizing collection...")
            result = creator.optimize_collection()
        
        # Print results
        print(f"\nResult: {'SUCCESS' if result.get('success', False) else 'FAILED'}")
        print(f"Message: {result.get('message', 'No message')}")
        
        if result.get('errors'):
            print("\nErrors:")
            for error in result['errors']:
                print(f"  - {error}")
        
        if result.get('details'):
            print(f"\nDetails: {result['details']}")
        
        # Exit with appropriate code
        sys.exit(0 if result.get('success', False) else 1)
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"Error: {e}")
        sys.exit(1)


# Async interface for integration with other services
async def create_collection_async(
    force: bool = False,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Async wrapper for collection creation
    
    Args:
        force: Force recreate if exists
        dry_run: Validate only
        
    Returns:
        Dict[str, Any]: Creation result
    """
    def run_sync():
        creator = CollectionCreator()
        return creator.create_collection(force=force, dry_run=dry_run)
    
    # Run in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_sync)


# Utility functions for other modules
def ensure_collection_exists() -> bool:
    """
    Ensure the medical_documents collection exists and is ready
    
    Returns:
        bool: True if collection exists and is ready
    """
    try:
        creator = CollectionCreator()
        creator.connect()
        
        if not creator.check_collection_exists():
            logger.info("Collection does not exist, creating...")
            result = creator.create_collection()
            return result['success']
        
        # Collection exists, check if it's loaded and optimized
        status = creator.get_collection_status()
        if status.get('exists', False):
            logger.info("Collection exists and is ready")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Failed to ensure collection exists: {e}")
        return False


def get_collection_health() -> Dict[str, Any]:
    """
    Get comprehensive collection health information
    
    Returns:
        Dict[str, Any]: Health information
    """
    try:
        creator = CollectionCreator()
        status = creator.get_collection_status()
        
        if status.get('exists', False):
            # Add health-specific checks
            status['health'] = {
                'status': 'healthy' if status.get('schema_valid', False) else 'unhealthy',
                'ready_for_queries': bool(status.get('num_entities', 0) >= 0),
                'index_configured': len(status.get('indexes', [])) > 0,
                'loaded': not status.get('is_empty', True)
            }
        else:
            status['health'] = {
                'status': 'missing',
                'ready_for_queries': False,
                'index_configured': False,
                'loaded': False
            }
        
        return status
        
    except Exception as e:
        return {
            'exists': False,
            'health': {
                'status': 'error',
                'ready_for_queries': False,
                'index_configured': False,
                'loaded': False
            },
            'error': str(e)
        }


if __name__ == "__main__":
    main()