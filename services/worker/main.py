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
from handlers.base import WorkerPool, BaseHandler


# Import specific handlers
from handlers.document_handler import DocumentHandler
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
        self.logger = logging.getLogger("worker.service")
        
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
            max_workers=self.config.max_document_workers
        )
        self.pool.add_handler(document_handler)
        
        # Embedding generation handler
        embedding_handler = EmbeddingHandler(
            handler_name="embedding-generator", 
            max_workers=self.config.max_embedding_workers
        )
        self.pool.add_handler(embedding_handler)
        
        # Question processing handler
        answer_handler = AnswerHandler(
            handler_name="question-processor",
            max_workers=self.config.max_question_workers
        )
        self.pool.add_handler(answer_handler)
        
        # Note: Additional handlers (embedding, question) will be added as they are implemented
        
        self.logger.info(f"Configured {len(self.pool.handlers)} handlers")
    
    async def start(self) -> bool:
        """
        Start the worker service
        
        Returns:
            bool: True if service started successfully
        """
        self.logger.info("Starting RAG Worker Service...")
        
        try:
            # Setup handlers
            self.setup_handlers()
            
            # Start handler pool
            if not await self.pool.start_all():
                self.logger.error("Failed to start handler pool")
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
        
        return {
            'status': 'healthy' if self.pool.is_running else 'stopped',
            'service_info': self.service_info,
            'uptime': uptime.total_seconds(),
            'handlers': stats,
            'timestamp': datetime.now().isoformat()
        }


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


def setup_logging():
    """Setup logging configuration"""
    config = get_config()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('worker.log') if config.environment == 'production' else logging.NullHandler()
        ]
    )
    
    # Set specific logger levels
    if config.environment == 'development':
        logging.getLogger('worker').setLevel(logging.DEBUG)
    elif config.environment == 'production':
        # Reduce noise in production
        logging.getLogger('nats').setLevel(logging.WARNING)
        logging.getLogger('pymilvus').setLevel(logging.WARNING)


async def main():
    """Main entry point"""
    # Setup logging
    setup_logging()
    logger = logging.getLogger("worker.main")
    
    try:
        logger.info("Initializing RAG Worker Service...")
        
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