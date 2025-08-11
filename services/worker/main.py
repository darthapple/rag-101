"""
RAG-101 Worker Service Main Entry Point

Multiprocessing architecture for concurrent document processing, embedding generation,
and Q&A processing using NATS messaging and specialized handlers.
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from typing import Dict, Any, List
import signal
import json
from datetime import datetime

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from shared.config import get_config
from shared.logging import setup_logging, get_structured_logger
from shared.infrastructure import InfrastructureManager
from handlers.base import WorkerPool, BaseHandler


# Import specific handlers
from handlers.document_handler import DocumentHandler
from handlers.chunk_handler import ChunkHandler
from handlers.embedding_handler import EmbeddingHandler
from handlers.answer_handler import AnswerHandler


class WorkerService:
    """
    Main worker service that manages the multiprocessing architecture
    and coordinates all handler types for the RAG system.
    """
    
    def __init__(self):
        """Initialize the worker service"""
        self.config = get_config()
        self.pool = WorkerPool()
        self.start_time = datetime.now()
        self.logger = get_structured_logger("worker.service", "rag-worker")
        self.infra_manager = None
        
        # Service metadata
        self.service_info = {
            'service_name': 'rag-worker',
            'version': '0.1.0',
            'start_time': self.start_time.isoformat(),
            'config': {
                'max_document_workers': self.config.max_document_workers,
                'max_embedding_workers': self.config.max_embedding_workers,
                'max_question_workers': self.config.max_question_workers,
                'nats_url': self.config.nats_url,
                'milvus_host': self.config.milvus_host,
                'environment': self.config.environment
            }
        }
    
    def setup_handlers(self):
        """Set up all handler types with their configurations"""
        self.logger.info("Setting up worker handlers...")
        
        # Document processing handler
        document_handler = DocumentHandler(
            handler_name="document-processor",
            max_workers=self.config.max_document_workers,
            infra_manager=self.infra_manager
        )
        self.pool.add_handler(document_handler)
        
        # Chunk processing handler
        chunk_handler = ChunkHandler(
            handler_name="chunk-processor",
            max_workers=self.config.max_document_workers,  # Use same limit as document workers
            infra_manager=self.infra_manager
        )
        self.pool.add_handler(chunk_handler)
        
        # Embedding generation handler
        embedding_handler = EmbeddingHandler(
            handler_name="embedding-generator", 
            max_workers=self.config.max_embedding_workers,
            infra_manager=self.infra_manager
        )
        self.pool.add_handler(embedding_handler)
        
        # Question processing handler
        answer_handler = AnswerHandler(
            handler_name="question-processor",
            max_workers=self.config.max_question_workers,
            infra_manager=self.infra_manager
        )
        self.pool.add_handler(answer_handler)
        
        # Note: Additional handlers (embedding, question) will be added as they are implemented
        
        self.logger.info(
            "Handlers configured",
            handler_count=len(self.pool.handlers),
            handlers=[h.handler_name for h in self.pool.handlers],
            max_document_workers=self.config.max_document_workers,
            max_embedding_workers=self.config.max_embedding_workers,
            max_question_workers=self.config.max_question_workers
        )
    
    async def start(self) -> bool:
        """
        Start the worker service
        
        Returns:
            bool: True if service started successfully
        """
        self.logger.info(
            "Starting RAG Worker Service",
            service_name="rag-worker",
            version=self.service_info['version'],
            environment=self.config.environment,
            nats_url=self.config.nats_url
        )
        
        try:
            # Initialize infrastructure (NATS streams, Milvus collections)
            self.logger.info("Verifying infrastructure components...")
            self.infra_manager = InfrastructureManager(self.config, service_name="worker")
            
            # Initialize with partial failure allowed (worker can run with degraded functionality)
            infra_success = await self.infra_manager.initialize_all(require_all=False)
            
            if not infra_success:
                self.logger.warning(
                    "Infrastructure initialization partially failed",
                    status=self.infra_manager.get_status()
                )
                # Continue anyway - workers might still function partially
            else:
                self.logger.info(
                    "Infrastructure verification complete",
                    status=self.infra_manager.get_status()
                )
            
            # Setup handlers
            self.setup_handlers()
            
            # Start handler pool
            if not await self.pool.start_all():
                self.logger.error(
                "Failed to start handler pool",
                handler_count=len(self.pool.handlers),
                service_name="rag-worker"
            )
                return False
            
            # Log service startup
            self.logger.info(
                f"RAG Worker Service started successfully with {len(self.pool.handlers)} handlers"
            )
            
            # Print startup summary
            self._print_startup_summary()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start worker service: {e}", exc_info=True)
            return False
    
    async def run(self):
        """Run the worker service until shutdown"""
        try:
            if not await self.start():
                return False
            
            self.logger.info("Worker service running. Press Ctrl+C to stop.")
            
            # Wait for shutdown signal
            await self.pool.wait_for_shutdown()
            
            self.logger.info("Shutdown signal received, stopping service...")
            await self.stop()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error running worker service: {e}", exc_info=True)
            return False
    
    async def stop(self):
        """Stop the worker service gracefully"""
        self.logger.info("Stopping RAG Worker Service...")
        
        try:
            # Stop handler pool
            await self.pool.stop_all()
            
            # Cleanup infrastructure connections
            if self.infra_manager:
                await self.infra_manager.cleanup()
            
            # Log shutdown summary
            uptime = datetime.now() - self.start_time
            stats = self.pool.get_stats()
            
            self.logger.info(
                f"RAG Worker Service stopped. "
                f"Uptime: {uptime}, "
                f"Messages processed: {stats['totals']['messages_processed']}, "
                f"Errors: {stats['totals']['errors']}"
            )
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}", exc_info=True)
    
    def _print_startup_summary(self):
        """Print startup summary to console"""
        print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                           RAG-101 Worker Service                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Version: {self.service_info['version']:<63} ║
║ Environment: {self.config.environment:<59} ║
║ Start Time: {self.service_info['start_time']:<60} ║
║                                                                              ║
║ Configuration:                                                               ║
║   NATS URL: {self.config.nats_url:<60} ║
║   Milvus: {self.config.milvus_host}:{self.config.milvus_port:<53} ║
║   Infrastructure: {'Verified' if self.infra_manager else 'Not Verified':<61} ║
║   Document Workers: {self.config.max_document_workers:<54} ║
║   Embedding Workers: {self.config.max_embedding_workers:<53} ║
║   Question Workers: {self.config.max_question_workers:<55} ║
║                                                                              ║
║ Handlers: {len(self.pool.handlers):<66} ║
╚══════════════════════════════════════════════════════════════════════════════╝
        """.strip())
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get service health status
        
        Returns:
            Dict[str, Any]: Health status information
        """
        uptime = datetime.now() - self.start_time
        stats = self.pool.get_stats()
        
        health_status = {
            'status': 'healthy' if self.pool.is_running else 'stopped',
            'service_info': self.service_info,
            'uptime': uptime.total_seconds(),
            'handlers': stats,
            'timestamp': datetime.now().isoformat()
        }
        
        # Add infrastructure status if available
        if self.infra_manager:
            health_status['infrastructure'] = self.infra_manager.get_status()
        
        return health_status


class DummyHandler(BaseHandler):
    """
    Dummy handler for testing the framework
    TODO: Remove when actual handlers are implemented
    """
    
    async def process_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a test message"""
        self.logger.info(f"Processing dummy message: {data}")
        await asyncio.sleep(0.1)  # Simulate processing
        return {'status': 'processed', 'data': data}
    
    def get_subscription_subject(self) -> str:
        """Subscribe to test messages"""
        return "test.messages"
    
    def get_consumer_config(self) -> Dict[str, Any]:
        """Test consumer configuration"""
        return {
            'durable_name': 'test-consumer',
            'manual_ack': True,
            'pending_msgs_limit': 10
        }


def setup_worker_logging():
    """Setup comprehensive structured logging for worker service"""
    # Use shared structured logging setup
    logger = setup_logging("rag-worker")
    
    # Set specific logger levels for worker components
    config = get_config()
    if config.environment == 'development':
        logging.getLogger('worker').setLevel(logging.DEBUG)
        logging.getLogger('handlers').setLevel(logging.DEBUG)
    elif config.environment == 'production':
        # Reduce noise in production
        logging.getLogger('nats').setLevel(logging.WARNING)
        logging.getLogger('pymilvus').setLevel(logging.WARNING)
        logging.getLogger('langchain').setLevel(logging.WARNING)
        logging.getLogger('aiohttp').setLevel(logging.WARNING)
    
    return logger


async def main():
    """Main entry point"""
    # Setup structured logging
    logger = setup_worker_logging()
    
    try:
        logger.info(
            "Initializing RAG Worker Service",
            service_name="rag-worker",
            process_id=os.getpid()
        )
        
        # Create and run service
        service = WorkerService()
        success = await service.run()
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unhandled error in main: {e}", exc_info=True)
        sys.exit(1)


def cli_main():
    """CLI entry point for poetry script"""
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()