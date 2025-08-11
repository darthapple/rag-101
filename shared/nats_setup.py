"""
NATS JetStream configuration and setup utilities

This module provides comprehensive configuration for NATS JetStream topics,
KV stores, and consumer configurations for the RAG system's ephemeral messaging.
"""

import asyncio
import logging
import sys
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import timedelta

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

import nats
from nats.js import JetStreamContext
from nats.js.api import StreamConfig, ConsumerConfig, RetentionPolicy, StorageType, DiscardPolicy, DeliverPolicy, AckPolicy, ReplayPolicy
from nats.errors import TimeoutError as NATSTimeoutError

from shared.config import get_config

logger = logging.getLogger(__name__)


class NATSConfigurator:
    """
    NATS JetStream configuration manager
    
    Handles creation and management of JetStream topics, KV stores,
    and consumer configurations for the ephemeral messaging architecture.
    """
    
    def __init__(self, nats_url: Optional[str] = None):
        """
        Initialize NATS configurator
        
        Args:
            nats_url: Optional NATS server URL. Uses config if not provided.
        """
        self.config = get_config()
        self.nats_url = nats_url or self.config.nats_url
        self.nc = None
        self.js = None
        
        # Stream configurations
        self.streams = {
            'questions': {
                'name': 'questions',
                'subjects': ['questions', 'questions.>'],
                'description': 'User questions for processing',
                'max_age': timedelta(hours=1),
                'max_msgs': 10000,
                'storage': StorageType.MEMORY,
                'retention': RetentionPolicy.LIMITS,
                'discard': DiscardPolicy.OLD,
                'duplicate_window': timedelta(minutes=1)
            },
            'documents': {
                'name': 'documents',
                'subjects': ['documents.download', 'documents.process', 'documents.status'],
                'description': 'Document processing requests and status',
                'max_age': timedelta(hours=1),
                'max_msgs': 5000,
                'storage': StorageType.MEMORY,
                'retention': RetentionPolicy.LIMITS,
                'discard': DiscardPolicy.OLD
            },
            'embeddings': {
                'name': 'embeddings',
                'subjects': ['embeddings.create', 'embeddings.status', 'embeddings.complete'],
                'description': 'Embedding generation tasks',
                'max_age': timedelta(hours=1),
                'max_msgs': 50000,
                'storage': StorageType.MEMORY,
                'retention': RetentionPolicy.LIMITS,
                'discard': DiscardPolicy.OLD
            },
            'answers': {
                'name': 'answers',
                'subjects': ['answers.*'],
                'description': 'Session-specific answer delivery',
                'max_age': timedelta(hours=1),
                'max_msgs': 10000,
                'storage': StorageType.MEMORY,
                'retention': RetentionPolicy.LIMITS,
                'discard': DiscardPolicy.OLD
            },
            'system': {
                'name': 'system',
                'subjects': ['system.metrics', 'system.health', 'system.events'],
                'description': 'System monitoring and metrics',
                'max_age': timedelta(minutes=30),
                'max_msgs': 100000,
                'storage': StorageType.MEMORY,
                'retention': RetentionPolicy.LIMITS,
                'discard': DiscardPolicy.OLD
            }
        }
        
        # Consumer configurations
        self.consumers = {
            'question-worker': {
                'stream': 'questions',
                'durable_name': 'question-worker',
                'filter_subject': 'questions',
                'deliver_policy': DeliverPolicy.ALL,
                'ack_policy': AckPolicy.EXPLICIT,
                'max_deliver': 3,
                'ack_wait': timedelta(seconds=30),
                'max_ack_pending': 100,
                'description': 'Worker consumer for processing questions'
            },
            'document-worker': {
                'stream': 'documents',
                'durable_name': 'document-worker',
                'filter_subject': 'documents.download',
                'deliver_policy': DeliverPolicy.ALL,
                'ack_policy': AckPolicy.EXPLICIT,
                'max_deliver': 3,
                'ack_wait': timedelta(minutes=5),
                'max_ack_pending': 10,
                'description': 'Worker consumer for document processing'
            },
            'embedding-worker': {
                'stream': 'embeddings',
                'durable_name': 'embedding-worker',
                'filter_subject': 'embeddings.create',
                'deliver_policy': DeliverPolicy.ALL,
                'ack_policy': AckPolicy.EXPLICIT,
                'max_deliver': 3,
                'ack_wait': timedelta(minutes=2),
                'max_ack_pending': 50,
                'description': 'Worker consumer for embedding generation'
            },
            'answer-monitor': {
                'stream': 'answers',
                'durable_name': 'answer-monitor',
                'filter_subject': 'answers.>',
                'deliver_policy': DeliverPolicy.NEW,
                'ack_policy': AckPolicy.NONE,
                'max_deliver': 1,
                'description': 'Monitor consumer for answer tracking'
            },
            'metrics-collector': {
                'stream': 'system',
                'durable_name': 'metrics-collector',
                'filter_subject': 'system.metrics',
                'deliver_policy': DeliverPolicy.NEW,
                'ack_policy': AckPolicy.NONE,
                'max_deliver': 1,
                'description': 'Collector consumer for system metrics'
            }
        }
        
        # KV store configurations
        self.kv_stores = {
            'sessions': {
                'bucket': 'sessions',
                'description': 'Session data with TTL',
                'ttl': timedelta(hours=1),
                'max_value_size': 10240,  # 10KB
                'history': 1,  # Keep only latest value
                'storage': StorageType.MEMORY,
                'replicas': 1
            },
            'processing_status': {
                'bucket': 'processing_status',
                'description': 'Document and embedding processing status',
                'ttl': timedelta(hours=2),
                'max_value_size': 5120,  # 5KB
                'history': 5,  # Keep last 5 status updates
                'storage': StorageType.MEMORY,
                'replicas': 1
            },
            'cache': {
                'bucket': 'cache',
                'description': 'Temporary cache for frequently accessed data',
                'ttl': timedelta(minutes=15),
                'max_value_size': 102400,  # 100KB
                'history': 1,
                'storage': StorageType.MEMORY,
                'replicas': 1
            }
        }
    
    async def connect(self) -> bool:
        """
        Connect to NATS server
        
        Returns:
            bool: True if connection successful
        """
        try:
            self.nc = await nats.connect(
                servers=[self.nats_url],
                max_reconnect_attempts=self.config.max_reconnect_attempts,
                reconnect_time_wait=self.config.reconnect_time_wait,
                ping_interval=self.config.ping_interval,
                max_outstanding_pings=self.config.max_outstanding_pings
            )
            
            self.js = self.nc.jetstream()
            logger.info(f"Connected to NATS at {self.nats_url}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from NATS server"""
        if self.nc and not self.nc.is_closed:
            await self.nc.close()
            logger.info("Disconnected from NATS")
    
    async def create_stream(self, stream_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create or update a JetStream stream
        
        Args:
            stream_config: Stream configuration dictionary
            
        Returns:
            Dict[str, Any]: Creation result
        """
        result = {
            'success': False,
            'stream_name': stream_config['name'],
            'created': False,
            'updated': False,
            'message': '',
            'info': None
        }
        
        try:
            # Build stream configuration
            config = StreamConfig(
                name=stream_config['name'],
                subjects=stream_config['subjects'],
                description=stream_config.get('description', ''),
                retention=stream_config.get('retention', RetentionPolicy.LIMITS),
                max_msgs=stream_config.get('max_msgs', 10000),
                max_age=stream_config.get('max_age', timedelta(hours=1)).total_seconds(),
                storage=stream_config.get('storage', StorageType.MEMORY),
                discard=stream_config.get('discard', DiscardPolicy.OLD),
                duplicate_window=stream_config.get('duplicate_window', timedelta(minutes=1)).total_seconds() * 1_000_000_000  # Convert to nanoseconds
            )
            
            # Check if stream exists
            try:
                existing_info = await self.js.stream_info(stream_config['name'])
                # Update existing stream
                stream_info = await self.js.update_stream(config=config)
                result['updated'] = True
                result['message'] = f"Updated stream '{stream_config['name']}'"
                logger.info(f"Updated stream '{stream_config['name']}'")
                
            except Exception:
                # Create new stream
                stream_info = await self.js.add_stream(config=config)
                result['created'] = True
                result['message'] = f"Created stream '{stream_config['name']}'"
                logger.info(f"Created stream '{stream_config['name']}' with subjects {stream_config['subjects']}")
            
            result['success'] = True
            result['info'] = {
                'name': stream_info.config.name,
                'subjects': stream_info.config.subjects,
                'state': {
                    'messages': stream_info.state.messages,
                    'bytes': stream_info.state.bytes,
                    'first_seq': stream_info.state.first_seq,
                    'last_seq': stream_info.state.last_seq
                }
            }
            
        except Exception as e:
            result['message'] = f"Failed to create/update stream: {str(e)}"
            logger.error(result['message'])
        
        return result
    
    async def create_consumer(self, consumer_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a JetStream consumer
        
        Args:
            consumer_config: Consumer configuration dictionary
            
        Returns:
            Dict[str, Any]: Creation result
        """
        result = {
            'success': False,
            'consumer_name': consumer_config['durable_name'],
            'stream': consumer_config['stream'],
            'created': False,
            'message': '',
            'info': None
        }
        
        try:
            # Build consumer configuration
            config = ConsumerConfig(
                durable_name=consumer_config['durable_name'],
                filter_subject=consumer_config.get('filter_subject'),
                deliver_policy=consumer_config.get('deliver_policy', DeliverPolicy.ALL),
                ack_policy=consumer_config.get('ack_policy', AckPolicy.EXPLICIT),
                max_deliver=consumer_config.get('max_deliver', 3),
                ack_wait=consumer_config.get('ack_wait', timedelta(seconds=30)).total_seconds(),
                max_ack_pending=consumer_config.get('max_ack_pending', 100),
                description=consumer_config.get('description', ''),
                replay_policy=ReplayPolicy.INSTANT
            )
            
            # Create consumer
            consumer_info = await self.js.add_consumer(
                stream=consumer_config['stream'],
                config=config
            )
            
            result['success'] = True
            result['created'] = True
            result['message'] = f"Created consumer '{consumer_config['durable_name']}' on stream '{consumer_config['stream']}'"
            result['info'] = {
                'name': consumer_info.name,
                'stream': consumer_info.stream_name,
                'num_pending': consumer_info.num_pending,
                'num_ack_pending': consumer_info.num_ack_pending
            }
            
            logger.info(result['message'])
            
        except Exception as e:
            # Consumer might already exist, which is okay
            if "already exists" in str(e).lower():
                result['message'] = f"Consumer '{consumer_config['durable_name']}' already exists"
                logger.info(result['message'])
            else:
                result['message'] = f"Failed to create consumer: {str(e)}"
                logger.error(result['message'])
        
        return result
    
    async def create_kv_store(self, kv_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a JetStream KV store
        
        Args:
            kv_config: KV store configuration dictionary
            
        Returns:
            Dict[str, Any]: Creation result
        """
        result = {
            'success': False,
            'bucket': kv_config['bucket'],
            'created': False,
            'message': '',
            'info': None
        }
        
        try:
            # Create KV bucket configuration
            kv = await self.js.create_key_value(
                bucket=kv_config['bucket'],
                description=kv_config.get('description', ''),
                ttl=kv_config.get('ttl', timedelta(hours=1)).total_seconds(),
                max_value_size=kv_config.get('max_value_size', 10240),
                history=kv_config.get('history', 1),
                storage=kv_config.get('storage', StorageType.MEMORY),
                replicas=kv_config.get('replicas', 1)
            )
            
            result['success'] = True
            result['created'] = True
            result['message'] = f"Created KV store '{kv_config['bucket']}'"
            
            # Get bucket status
            status = await kv.status()
            result['info'] = {
                'bucket': status.bucket,
                'values': status.values,
                'bytes': status.bytes,
                'ttl': kv_config.get('ttl', timedelta(hours=1)).total_seconds()
            }
            
            logger.info(f"Created KV store '{kv_config['bucket']}' with TTL {kv_config.get('ttl', timedelta(hours=1))}")
            
        except Exception as e:
            # KV store might already exist
            if "already in use" in str(e).lower() or "already exists" in str(e).lower():
                result['message'] = f"KV store '{kv_config['bucket']}' already exists"
                logger.info(result['message'])
                
                # Try to get existing KV store info
                try:
                    kv = await self.js.key_value(bucket=kv_config['bucket'])
                    status = await kv.status()
                    result['info'] = {
                        'bucket': status.bucket,
                        'values': status.values,
                        'bytes': status.bytes
                    }
                except:
                    pass
            else:
                result['message'] = f"Failed to create KV store: {str(e)}"
                logger.error(result['message'])
        
        return result
    
    async def setup_all_streams(self) -> Dict[str, Any]:
        """
        Create all configured JetStream streams
        
        Returns:
            Dict[str, Any]: Results for all stream creations
        """
        results = {
            'success': True,
            'streams_created': [],
            'streams_updated': [],
            'streams_failed': [],
            'details': {}
        }
        
        for stream_name, stream_config in self.streams.items():
            logger.info(f"Setting up stream: {stream_name}")
            result = await self.create_stream(stream_config)
            
            results['details'][stream_name] = result
            
            if result['success']:
                if result['created']:
                    results['streams_created'].append(stream_name)
                elif result['updated']:
                    results['streams_updated'].append(stream_name)
            else:
                results['streams_failed'].append(stream_name)
                results['success'] = False
        
        logger.info(f"Stream setup complete - Created: {len(results['streams_created'])}, "
                   f"Updated: {len(results['streams_updated'])}, Failed: {len(results['streams_failed'])}")
        
        return results
    
    async def setup_all_consumers(self) -> Dict[str, Any]:
        """
        Create all configured consumers
        
        Returns:
            Dict[str, Any]: Results for all consumer creations
        """
        results = {
            'success': True,
            'consumers_created': [],
            'consumers_failed': [],
            'details': {}
        }
        
        for consumer_name, consumer_config in self.consumers.items():
            logger.info(f"Setting up consumer: {consumer_name}")
            result = await self.create_consumer(consumer_config)
            
            results['details'][consumer_name] = result
            
            if result['created']:
                results['consumers_created'].append(consumer_name)
            elif not result['success']:
                results['consumers_failed'].append(consumer_name)
                results['success'] = False
        
        logger.info(f"Consumer setup complete - Created: {len(results['consumers_created'])}, "
                   f"Failed: {len(results['consumers_failed'])}")
        
        return results
    
    async def setup_all_kv_stores(self) -> Dict[str, Any]:
        """
        Create all configured KV stores
        
        Returns:
            Dict[str, Any]: Results for all KV store creations
        """
        results = {
            'success': True,
            'kv_stores_created': [],
            'kv_stores_failed': [],
            'details': {}
        }
        
        for kv_name, kv_config in self.kv_stores.items():
            logger.info(f"Setting up KV store: {kv_name}")
            result = await self.create_kv_store(kv_config)
            
            results['details'][kv_name] = result
            
            if result['created']:
                results['kv_stores_created'].append(kv_name)
            elif not result['success']:
                results['kv_stores_failed'].append(kv_name)
                results['success'] = False
        
        logger.info(f"KV store setup complete - Created: {len(results['kv_stores_created'])}, "
                   f"Failed: {len(results['kv_stores_failed'])}")
        
        return results
    
    async def setup_complete_infrastructure(self) -> Dict[str, Any]:
        """
        Set up complete NATS JetStream infrastructure
        
        Returns:
            Dict[str, Any]: Complete setup results
        """
        results = {
            'success': False,
            'connected': False,
            'streams': None,
            'consumers': None,
            'kv_stores': None,
            'message': ''
        }
        
        try:
            # Connect to NATS
            if not await self.connect():
                results['message'] = "Failed to connect to NATS"
                return results
            
            results['connected'] = True
            
            # Set up streams
            logger.info("Setting up JetStream streams...")
            results['streams'] = await self.setup_all_streams()
            
            # Set up consumers
            logger.info("Setting up consumers...")
            results['consumers'] = await self.setup_all_consumers()
            
            # Set up KV stores
            logger.info("Setting up KV stores...")
            results['kv_stores'] = await self.setup_all_kv_stores()
            
            # Check overall success
            results['success'] = (
                results['streams']['success'] and
                results['consumers']['success'] and
                results['kv_stores']['success']
            )
            
            if results['success']:
                results['message'] = "NATS JetStream infrastructure setup completed successfully"
            else:
                results['message'] = "NATS JetStream infrastructure setup completed with some failures"
            
            logger.info(results['message'])
            
        except Exception as e:
            results['message'] = f"Infrastructure setup failed: {str(e)}"
            logger.error(results['message'], exc_info=True)
        
        finally:
            await self.disconnect()
        
        return results
    
    async def get_infrastructure_status(self) -> Dict[str, Any]:
        """
        Get status of all NATS infrastructure components
        
        Returns:
            Dict[str, Any]: Status information
        """
        status = {
            'connected': False,
            'streams': {},
            'consumers': {},
            'kv_stores': {},
            'message': ''
        }
        
        try:
            if not await self.connect():
                status['message'] = "Failed to connect to NATS"
                return status
            
            status['connected'] = True
            
            # Get stream status
            for stream_name in self.streams.keys():
                try:
                    info = await self.js.stream_info(stream_name)
                    status['streams'][stream_name] = {
                        'exists': True,
                        'messages': info.state.messages,
                        'bytes': info.state.bytes,
                        'consumer_count': info.state.consumer_count
                    }
                except:
                    status['streams'][stream_name] = {'exists': False}
            
            # Get consumer status
            for consumer_name, consumer_config in self.consumers.items():
                try:
                    info = await self.js.consumer_info(
                        stream=consumer_config['stream'],
                        consumer=consumer_config['durable_name']
                    )
                    status['consumers'][consumer_name] = {
                        'exists': True,
                        'pending': info.num_pending,
                        'ack_pending': info.num_ack_pending,
                        'delivered': info.delivered
                    }
                except:
                    status['consumers'][consumer_name] = {'exists': False}
            
            # Get KV store status
            for kv_name in self.kv_stores.keys():
                try:
                    kv = await self.js.key_value(bucket=kv_name)
                    kv_status = await kv.status()
                    status['kv_stores'][kv_name] = {
                        'exists': True,
                        'values': kv_status.values,
                        'bytes': kv_status.bytes
                    }
                except:
                    status['kv_stores'][kv_name] = {'exists': False}
            
            status['message'] = "Infrastructure status retrieved successfully"
            
        except Exception as e:
            status['message'] = f"Failed to get infrastructure status: {str(e)}"
            logger.error(status['message'])
        
        finally:
            await self.disconnect()
        
        return status
    
    async def cleanup_infrastructure(self, force: bool = False) -> Dict[str, Any]:
        """
        Clean up NATS infrastructure (useful for testing/reset)
        
        Args:
            force: If True, delete all streams and KV stores
            
        Returns:
            Dict[str, Any]: Cleanup results
        """
        results = {
            'success': False,
            'streams_deleted': [],
            'kv_stores_deleted': [],
            'message': ''
        }
        
        if not force:
            results['message'] = "Cleanup requires force=True to prevent accidental deletion"
            return results
        
        try:
            if not await self.connect():
                results['message'] = "Failed to connect to NATS"
                return results
            
            # Delete streams
            for stream_name in self.streams.keys():
                try:
                    await self.js.delete_stream(stream_name)
                    results['streams_deleted'].append(stream_name)
                    logger.info(f"Deleted stream: {stream_name}")
                except Exception as e:
                    logger.warning(f"Failed to delete stream {stream_name}: {e}")
            
            # Delete KV stores
            for kv_name in self.kv_stores.keys():
                try:
                    await self.js.delete_key_value(kv_name)
                    results['kv_stores_deleted'].append(kv_name)
                    logger.info(f"Deleted KV store: {kv_name}")
                except Exception as e:
                    logger.warning(f"Failed to delete KV store {kv_name}: {e}")
            
            results['success'] = True
            results['message'] = f"Cleanup completed - Deleted {len(results['streams_deleted'])} streams, {len(results['kv_stores_deleted'])} KV stores"
            
        except Exception as e:
            results['message'] = f"Cleanup failed: {str(e)}"
            logger.error(results['message'])
        
        finally:
            await self.disconnect()
        
        return results


# CLI Interface
async def main():
    """Main CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="NATS JetStream configuration utility"
    )
    parser.add_argument(
        "action",
        choices=['setup', 'status', 'cleanup', 'streams', 'consumers', 'kv'],
        help="Action to perform"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force cleanup (required for cleanup action)"
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
    
    # Create configurator
    configurator = NATSConfigurator()
    
    try:
        if args.action == 'setup':
            print("Setting up NATS JetStream infrastructure...")
            result = await configurator.setup_complete_infrastructure()
            
        elif args.action == 'status':
            print("Getting infrastructure status...")
            result = await configurator.get_infrastructure_status()
            
        elif args.action == 'cleanup':
            if not args.force:
                print("Cleanup requires --force flag to prevent accidental deletion")
                sys.exit(1)
            print("Cleaning up NATS infrastructure...")
            result = await configurator.cleanup_infrastructure(force=True)
            
        elif args.action == 'streams':
            print("Setting up JetStream streams only...")
            await configurator.connect()
            result = await configurator.setup_all_streams()
            await configurator.disconnect()
            
        elif args.action == 'consumers':
            print("Setting up consumers only...")
            await configurator.connect()
            result = await configurator.setup_all_consumers()
            await configurator.disconnect()
            
        elif args.action == 'kv':
            print("Setting up KV stores only...")
            await configurator.connect()
            result = await configurator.setup_all_kv_stores()
            await configurator.disconnect()
        
        # Print results
        print(f"\nResult: {'SUCCESS' if result.get('success', False) else 'FAILED'}")
        print(f"Message: {result.get('message', 'No message')}")
        
        # Print detailed results
        if args.verbose:
            print("\nDetailed Results:")
            print(json.dumps(result, indent=2, default=str))
        
        # Exit with appropriate code
        sys.exit(0 if result.get('success', False) else 1)
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())