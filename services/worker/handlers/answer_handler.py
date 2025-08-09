"""
Answer Handler

Processes user questions through a complete RAG pipeline:
1. Receives questions from NATS
2. Generates embeddings for the question
3. Performs vector similarity search in Milvus
4. Constructs RAG context from retrieved documents
5. Generates answers using Google Gemini
6. Publishes answers to session-specific topics
"""

import asyncio
import logging
import sys
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import json
import uuid
import re

from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.schema import HumanMessage, SystemMessage
from langchain.prompts import PromptTemplate
import google.generativeai as genai

from handlers.base import BaseHandler, MessageProcessingError
sys.path.append('/Users/fadriano/Projetos/Demos/rag-101')
from shared.database import MilvusDatabase, MilvusConnectionError, MilvusOperationError
from shared.models import Question, Answer, AnswerSource


class QuestionProcessingError(Exception):
    """Exception raised during question processing"""
    pass


class AnswerGenerationError(Exception):
    """Exception raised during answer generation"""
    pass


class AnswerHandler(BaseHandler):
    """
    Handler for Q&A processing using RAG pipeline:
    1. Consumes questions from 'questions' topic
    2. Generates embedding for the question
    3. Searches Milvus for relevant document chunks
    4. Constructs context from retrieved documents
    5. Generates answer using Gemini Pro
    6. Publishes to session-specific answer topics
    """
    
    def __init__(self, handler_name: str = "answer-handler", max_workers: int = 2):
        """
        Initialize answer handler
        
        Args:
            handler_name: Handler identifier
            max_workers: Maximum concurrent workers
        """
        super().__init__(handler_name, max_workers)
        
        # Configuration
        self.question_timeout = self.config.question_timeout
        self.max_retries = self.config.max_retries
        
        # RAG configuration
        self.top_k_documents = 5  # Number of documents to retrieve
        self.max_context_length = 4000  # Maximum context length for generation
        self.embedding_model = self.config.embedding_model
        self.chat_model = self.config.chat_model
        
        # Initialize Gemini clients
        self.embeddings_client = None
        self.chat_client = None
        self._setup_gemini_clients()
        
        # Initialize Milvus database
        self.milvus_db = MilvusDatabase(
            host=self.config.milvus_host,
            port=self.config.milvus_port,
            alias=f"{self.handler_name}-milvus",
            timeout=self.config.connection_timeout
        )
        
        # RAG prompt template
        self.rag_prompt = PromptTemplate(
            template="""Você é um assistente médico especializado em protocolos clínicos brasileiros. 
Use apenas as informações fornecidas no contexto para responder à pergunta do usuário.

CONTEXTO:
{context}

PERGUNTA: {question}

INSTRUÇÕES:
- Responda apenas com base nas informações do contexto fornecido
- Se a informação não estiver no contexto, diga "Não tenho informações suficientes para responder essa pergunta com base nos documentos fornecidos"
- Seja preciso e cite as fontes quando relevante
- Use linguagem clara e acessível
- Mantenha o foco em protocolos clínicos e diretrizes médicas brasileiras

RESPOSTA:""",
            input_variables=["context", "question"]
        )
        
        self.logger.info(f"Answer handler initialized with models: {self.embedding_model}, {self.chat_model}")
    
    def _setup_gemini_clients(self):
        """Setup Google Gemini API clients"""
        try:
            if not self.config.google_api_key:
                raise AnswerGenerationError("GOOGLE_API_KEY not configured")
            
            # Configure Gemini API
            genai.configure(api_key=self.config.google_api_key)
            
            # Initialize embeddings client for question embedding
            self.embeddings_client = GoogleGenerativeAIEmbeddings(
                model=self.embedding_model,
                google_api_key=self.config.google_api_key,
                task_type="retrieval_query",  # Optimized for search queries
                title="Medical Question Embedding"
            )
            
            # Initialize chat client for answer generation
            self.chat_client = ChatGoogleGenerativeAI(
                model=self.chat_model,
                google_api_key=self.config.google_api_key,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                top_p=self.config.top_p,
                top_k=self.config.top_k
            )
            
            self.logger.info(f"Gemini clients initialized: {self.embedding_model}, {self.chat_model}")
            
        except Exception as e:
            self.logger.error(f"Failed to setup Gemini clients: {e}")
            raise AnswerGenerationError(f"Gemini clients setup failed: {e}")
    
    def get_subscription_subject(self) -> str:
        """Subscribe to questions topic"""
        return "questions"
    
    def get_consumer_config(self) -> Dict[str, Any]:
        """Consumer configuration for question processing"""
        return {
            'durable_name': 'question-processor',
            'manual_ack': True,
            'pending_msgs_limit': self.max_workers * 3,
            'ack_wait': self.question_timeout * 2
        }
    
    def get_result_subject(self, data: Dict[str, Any]) -> Optional[str]:
        """Publish answers to session-specific topics"""
        session_id = data.get('session_id')
        if session_id:
            return f"answers.{session_id}"
        return None
    
    async def process_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process question through RAG pipeline
        
        Args:
            data: Message data containing question and session info
            
        Returns:
            Dict[str, Any]: Generated answer with sources
            
        Raises:
            MessageProcessingError: If processing fails
        """
        start_time = datetime.now()
        
        try:
            # Extract question data
            session_id = data.get('session_id')
            question_text = data.get('question', '').strip()
            message_id = data.get('message_id', str(uuid.uuid4()))
            context = data.get('context', {})
            
            if not session_id:
                raise MessageProcessingError("Missing 'session_id' in message data")
            
            if not question_text:
                raise MessageProcessingError("Missing or empty 'question' in message data")
            
            self.logger.info(f"Processing question for session {session_id}: {question_text[:100]}...")
            
            # Connect to Milvus
            await self._ensure_milvus_connection()
            
            # Step 1: Generate embedding for the question
            question_embedding = await self._generate_question_embedding(question_text)
            
            # Step 2: Perform vector similarity search
            retrieved_chunks = await self._search_similar_documents(
                question_embedding, 
                question_text
            )
            
            # Step 3: Construct RAG context
            rag_context = await self._construct_rag_context(
                retrieved_chunks, 
                question_text
            )
            
            # Step 4: Generate answer using Gemini
            answer_data = await self._generate_answer(
                question_text, 
                rag_context, 
                retrieved_chunks
            )
            
            # Step 5: Prepare response
            processing_time = (datetime.now() - start_time).total_seconds()
            
            result = {
                'message_id': str(uuid.uuid4()),
                'session_id': session_id,
                'question_id': message_id,
                'question': question_text,
                'answer': answer_data['answer'],
                'sources': answer_data['sources'],
                'generated_at': datetime.now().isoformat(),
                'confidence_score': answer_data.get('confidence_score'),
                'model_used': self.chat_model,
                'processing_time': processing_time,
                'metadata': {
                    'chunks_retrieved': len(retrieved_chunks),
                    'context_length': len(rag_context),
                    'processing_steps': {
                        'embedding_generated': True,
                        'documents_retrieved': len(retrieved_chunks) > 0,
                        'context_constructed': len(rag_context) > 0,
                        'answer_generated': len(answer_data['answer']) > 0
                    }
                }
            }
            
            self.logger.info(
                f"Generated answer for session {session_id} in {processing_time:.2f}s "
                f"(retrieved {len(retrieved_chunks)} chunks)"
            )
            
            return result
            
        except QuestionProcessingError as e:
            error_msg = f"Question processing failed: {str(e)}"
            self.logger.error(error_msg)
            raise MessageProcessingError(error_msg)
            
        except AnswerGenerationError as e:
            error_msg = f"Answer generation failed: {str(e)}"
            self.logger.error(error_msg)
            raise MessageProcessingError(error_msg)
            
        except Exception as e:
            error_msg = f"Unexpected error in answer processing: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MessageProcessingError(error_msg)
    
    async def _ensure_milvus_connection(self):
        """Ensure Milvus connection is established"""
        try:
            if not self.milvus_db._connected:
                success = self.milvus_db.connect()
                if not success:
                    raise QuestionProcessingError("Failed to connect to Milvus")
            
            # Ensure collection exists
            if not self.milvus_db.collection_exists():
                raise QuestionProcessingError("Milvus collection does not exist")
            
        except Exception as e:
            raise QuestionProcessingError(f"Milvus connection error: {e}")
    
    async def _generate_question_embedding(self, question: str) -> List[float]:
        """
        Generate embedding for the user question
        
        Args:
            question: User question text
            
        Returns:
            List[float]: Question embedding vector
            
        Raises:
            QuestionProcessingError: If embedding generation fails
        """
        try:
            self.logger.debug(f"Generating embedding for question: {question[:50]}...")
            
            # Generate embedding with retry logic
            for attempt in range(self.max_retries):
                try:
                    # Use asyncio to run the sync embedding method
                    embeddings = await asyncio.get_event_loop().run_in_executor(
                        None,
                        self.embeddings_client.embed_query,
                        question
                    )
                    
                    # Validate embedding
                    if not embeddings or len(embeddings) != self.config.vector_dimension:
                        raise QuestionProcessingError(
                            f"Invalid embedding dimension: {len(embeddings) if embeddings else 0}"
                        )
                    
                    self.logger.debug("Question embedding generated successfully")
                    return embeddings
                    
                except Exception as e:
                    self.logger.warning(f"Embedding attempt {attempt + 1} failed: {e}")
                    
                    if attempt < self.max_retries - 1:
                        # Exponential backoff
                        wait_time = (2 ** attempt) * 1.0
                        await asyncio.sleep(wait_time)
                    else:
                        raise QuestionProcessingError(
                            f"Failed to generate question embedding after {self.max_retries} attempts: {e}"
                        )
            
            raise QuestionProcessingError("Failed to generate question embedding")
            
        except Exception as e:
            raise QuestionProcessingError(f"Question embedding failed: {e}")
    
    async def _search_similar_documents(
        self, 
        question_embedding: List[float], 
        question_text: str
    ) -> List[Dict[str, Any]]:
        """
        Search for similar document chunks in Milvus
        
        Args:
            question_embedding: Question embedding vector
            question_text: Original question text for filtering
            
        Returns:
            List[Dict[str, Any]]: Retrieved document chunks with metadata
            
        Raises:
            QuestionProcessingError: If search fails
        """
        try:
            self.logger.debug(f"Searching for {self.top_k_documents} similar documents")
            
            # Perform similarity search
            search_results = self.milvus_db.similarity_search(
                query_vector=question_embedding,
                top_k=self.top_k_documents,
                output_fields=[
                    "chunk_id", "text_content", "document_title",
                    "source_url", "page_number", "diseases", 
                    "processed_at", "job_id"
                ]
            )
            
            if not search_results:
                self.logger.warning("No similar documents found")
                return []
            
            # Process and enrich search results
            processed_results = []
            for result in search_results:
                # Parse diseases JSON
                diseases = []
                try:
                    if result.get('diseases'):
                        diseases = json.loads(result['diseases'])
                except json.JSONDecodeError:
                    diseases = []
                
                processed_result = {
                    'chunk_id': result.get('chunk_id', ''),
                    'text_content': result.get('text_content', ''),
                    'document_title': result.get('document_title', ''),
                    'source_url': result.get('source_url', ''),
                    'page_number': result.get('page_number', 1),
                    'diseases': diseases,
                    'relevance_score': result.get('score', 0.0),
                    'distance': result.get('distance', 1.0),
                    'processed_at': result.get('processed_at', ''),
                    'job_id': result.get('job_id', '')
                }
                
                processed_results.append(processed_result)
            
            self.logger.info(f"Retrieved {len(processed_results)} similar documents")
            return processed_results
            
        except (MilvusConnectionError, MilvusOperationError) as e:
            raise QuestionProcessingError(f"Milvus search error: {e}")
        except Exception as e:
            raise QuestionProcessingError(f"Document search failed: {e}")
    
    async def _construct_rag_context(
        self, 
        retrieved_chunks: List[Dict[str, Any]], 
        question: str
    ) -> str:
        """
        Construct RAG context from retrieved document chunks
        
        Args:
            retrieved_chunks: Retrieved document chunks
            question: Original question for context relevance
            
        Returns:
            str: Formatted context for answer generation
        """
        try:
            if not retrieved_chunks:
                return "Nenhum documento relevante encontrado."
            
            context_parts = []
            total_length = 0
            
            for i, chunk in enumerate(retrieved_chunks, 1):
                # Format chunk information
                chunk_text = chunk.get('text_content', '').strip()
                document_title = chunk.get('document_title', 'Documento sem título')
                page_number = chunk.get('page_number', 1)
                relevance_score = chunk.get('relevance_score', 0.0)
                
                # Create source attribution
                source_info = f"[Fonte {i}: {document_title}, Página {page_number}]"
                
                # Format chunk content
                chunk_content = f"{source_info}\n{chunk_text}"
                
                # Check if adding this chunk would exceed context limit
                chunk_length = len(chunk_content) + 50  # Buffer for formatting
                if total_length + chunk_length > self.max_context_length:
                    self.logger.debug(f"Context limit reached, including {i-1} chunks")
                    break
                
                context_parts.append(chunk_content)
                total_length += chunk_length
            
            # Combine all context parts
            context = "\n\n".join(context_parts)
            
            self.logger.debug(f"Constructed context with {len(context_parts)} chunks ({len(context)} chars)")
            return context
            
        except Exception as e:
            self.logger.error(f"Context construction failed: {e}")
            return "Erro na construção do contexto."
    
    async def _generate_answer(
        self, 
        question: str, 
        context: str, 
        retrieved_chunks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate answer using Gemini with RAG context
        
        Args:
            question: User question
            context: RAG context from retrieved documents
            retrieved_chunks: Original chunks for source attribution
            
        Returns:
            Dict[str, Any]: Answer data with sources and metadata
            
        Raises:
            AnswerGenerationError: If generation fails
        """
        try:
            self.logger.debug("Generating answer with Gemini Pro")
            
            # Format prompt using template
            formatted_prompt = self.rag_prompt.format(
                context=context,
                question=question
            )
            
            # Generate answer with retry logic
            answer_text = None
            for attempt in range(self.max_retries):
                try:
                    # Create messages for chat model
                    messages = [
                        SystemMessage(content="Você é um assistente médico especializado em protocolos clínicos brasileiros."),
                        HumanMessage(content=formatted_prompt)
                    ]
                    
                    # Generate response
                    response = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self.chat_client(messages)
                    )
                    
                    answer_text = response.content.strip()
                    
                    if answer_text:
                        break
                        
                except Exception as e:
                    self.logger.warning(f"Generation attempt {attempt + 1} failed: {e}")
                    
                    if attempt < self.max_retries - 1:
                        wait_time = (2 ** attempt) * 1.0
                        await asyncio.sleep(wait_time)
                    else:
                        raise AnswerGenerationError(
                            f"Failed to generate answer after {self.max_retries} attempts: {e}"
                        )
            
            if not answer_text:
                raise AnswerGenerationError("No answer generated")
            
            # Create source attributions
            sources = []
            for i, chunk in enumerate(retrieved_chunks[:5]):  # Limit to top 5 sources
                source = {
                    'chunk_id': chunk.get('chunk_id', ''),
                    'document_title': chunk.get('document_title', ''),
                    'source_url': chunk.get('source_url', ''),
                    'page_number': chunk.get('page_number', 1),
                    'relevance_score': chunk.get('relevance_score', 0.0),
                    'excerpt': chunk.get('text_content', '')[:200] + "...",  # First 200 chars
                    'diseases': chunk.get('diseases', [])
                }
                sources.append(source)
            
            # Calculate confidence score based on relevance scores
            if sources:
                avg_relevance = sum(s['relevance_score'] for s in sources) / len(sources)
                confidence_score = min(0.95, max(0.1, avg_relevance))  # Normalize to 0.1-0.95
            else:
                confidence_score = 0.1
            
            result = {
                'answer': answer_text,
                'sources': sources,
                'confidence_score': confidence_score
            }
            
            self.logger.info(f"Answer generated successfully ({len(answer_text)} chars, {len(sources)} sources)")
            return result
            
        except Exception as e:
            raise AnswerGenerationError(f"Answer generation failed: {e}")
    
    async def stop(self):
        """Stop the handler and cleanup connections"""
        await super().stop()
        
        # Disconnect from Milvus
        try:
            if self.milvus_db:
                self.milvus_db.disconnect()
                self.logger.info("Disconnected from Milvus")
        except Exception as e:
            self.logger.error(f"Error disconnecting from Milvus: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get handler statistics with RAG-specific metrics"""
        base_stats = super().get_stats()
        
        # Add RAG-specific stats
        base_stats.update({
            'embedding_model': self.embedding_model,
            'chat_model': self.chat_model,
            'top_k_documents': self.top_k_documents,
            'max_context_length': self.max_context_length,
            'milvus_connected': self.milvus_db._connected if self.milvus_db else False
        })
        
        return base_stats