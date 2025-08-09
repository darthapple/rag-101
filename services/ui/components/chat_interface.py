"""
Chat Interface Component

Interactive chat interface for Q&A with real-time answer streaming.
Handles question submission and displays conversation history using modern Streamlit chat components.
"""

import streamlit as st
import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException


class ChatInterface:
    """Interactive chat interface component with modern Streamlit chat UI"""
    
    def __init__(self, config: Dict[str, Any], session_id: str):
        """Initialize chat interface"""
        self.config = config
        self.session_id = session_id
        self.api_base_url = config['api_base_url']
        self.ws_base_url = config.get('ws_base_url', 'ws://localhost:8000')
        self.logger = logging.getLogger("ui.chat_interface")
    
    def render(self):
        """Render the chat interface"""
        # Render connection status
        self._render_connection_status()
        
        # Chat history display using modern st.chat_message
        self._render_chat_history()
        
        # Question input using st.chat_input
        self._render_question_input()
        
        # Help and examples
        with st.expander("💡 Ajuda & Exemplos"):
            self._render_help_section()
    
    def _render_connection_status(self):
        """Render connection status indicators"""
        status_col1, status_col2, status_col3 = st.columns(3)
        
        with status_col1:
            if st.session_state.get('api_connected', True):
                st.success("🟢 API Conectada")
            else:
                st.error("🔴 API Desconectada")
        
        with status_col2:
            if st.session_state.get('websocket_connected', False):
                st.success("🟢 WebSocket Ativo")
            else:
                st.warning("🟡 WebSocket Inativo")
        
        with status_col3:
            if st.session_state.get('processing_question', False):
                st.info("⏳ Processando...")
            else:
                st.success("✅ Pronto")
    
    def _render_chat_history(self):
        """Render chat message history using Streamlit's native chat components"""
        if not st.session_state.chat_history:
            # Welcome message with example questions
            st.chat_message("assistant").write("""
            👋 Olá! Sou o assistente médico do RAG-101. Posso ajudá-lo com perguntas sobre protocolos clínicos brasileiros (PCDT).
            
            **Exemplos de perguntas:**
            - Quais são os critérios diagnósticos para diabetes tipo 2?
            - Qual o tratamento recomendado para hipertensão arterial?
            - Quais são as contraindicações para uso de metformina?
            """)
            return
        
        # Render message history using st.chat_message
        for message in st.session_state.chat_history:
            message_type = message.get('type', 'user')
            content = message.get('content', '')
            timestamp = message.get('timestamp', '')
            
            if message_type == 'user':
                with st.chat_message("human"):
                    st.write(content)
                    if timestamp:
                        st.caption(f"🕐 {timestamp}")
            
            elif message_type == 'assistant':
                with st.chat_message("assistant"):
                    st.write(content)
                    
                    # Show confidence score if available
                    confidence = message.get('confidence_score')
                    if confidence:
                        confidence_color = "🟢" if confidence > 0.8 else "🟡" if confidence > 0.6 else "🟠"
                        st.caption(f"{confidence_color} Confiança: {confidence:.0%} • 🕐 {timestamp}")
                    elif timestamp:
                        st.caption(f"🕐 {timestamp}")
                    
                    # Show sources in an expander
                    sources = message.get('sources', [])
                    if sources:
                        with st.expander(f"📚 Fontes ({len(sources)} documentos)"):
                            for i, source in enumerate(sources, 1):
                                st.markdown(f"""
                                **{i}. {source.get('document_title', 'Documento desconhecido')}**
                                - **Relevância**: {source.get('relevance_score', 0):.1%}
                                - **Página**: {source.get('page_number', 'N/A')}
                                - **Trecho**: "{source.get('excerpt', 'Trecho não disponível')}"
                                """)
            
            elif message_type == 'error':
                with st.chat_message("assistant"):
                    st.error(f"❌ {content}")
                    if timestamp:
                        st.caption(f"🕐 {timestamp}")
            
            elif message_type == 'thinking':
                with st.chat_message("assistant"):
                    st.info(f"🤔 {content}")
                    if timestamp:
                        st.caption(f"🕐 {timestamp}")
    
    def _render_question_input(self):
        """Render modern question input using chat_input"""
        # Chat input at the bottom
        question = st.chat_input(
            placeholder="Digite sua pergunta sobre protocolos médicos...",
            key="chat_input",
            disabled=st.session_state.get('processing_question', False)
        )
        
        # Advanced options in expander
        with st.expander("⚙️ Opções Avançadas"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                priority = st.selectbox(
                    "Prioridade",
                    ["normal", "high", "low"],
                    index=0,
                    help="Prioridade da pergunta"
                )
            
            with col2:
                use_websocket = st.checkbox(
                    "Tempo Real",
                    value=True,
                    help="Receber resposta em tempo real via WebSocket"
                )
            
            with col3:
                if st.button("🗑️ Limpar Chat", type="secondary"):
                    st.session_state.chat_history = []
                    if 'processing_question' in st.session_state:
                        del st.session_state.processing_question
                    st.rerun()
        
        # Handle question submission
        if question and question.strip():
            self._submit_question(question.strip(), priority, use_websocket)
    
    def _submit_question(self, question: str, priority: str = "normal", use_websocket: bool = True):
        """Submit question to API service with real-time or polling mode"""
        try:
            import requests
            
            # Set processing flag
            st.session_state.processing_question = True
            
            # Add user message to chat history
            user_message = {
                'type': 'user',
                'content': question,
                'timestamp': datetime.now().strftime("%H:%M:%S")
            }
            st.session_state.chat_history.append(user_message)
            
            # Add thinking message
            self.add_thinking_message("Processando sua pergunta...")
            
            # Submit question to API
            payload = {
                "question": question,
                "priority": priority,
                "context": {
                    "use_websocket": use_websocket,
                    "ui_session": True
                }
            }
            
            headers = {
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                f"{self.api_base_url}/questions",
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 202:
                question_data = response.json()
                question_id = question_data['question_id']
                
                # Remove thinking message
                self.remove_thinking_message()
                
                if use_websocket:
                    # Try WebSocket for real-time answer
                    self._handle_realtime_answer(question_id)
                else:
                    # Fall back to polling
                    self._poll_for_answer(question_id, question)
            else:
                self.remove_thinking_message()
                error_msg = f"Falha ao enviar pergunta: {response.status_code}"
                self._add_error_message(error_msg)
        
        except Exception as e:
            self.logger.error(f"Question submission failed: {e}")
            self.remove_thinking_message()
            self._add_error_message(f"Erro ao enviar pergunta: {str(e)}")
        
        finally:
            # Clear processing flag
            st.session_state.processing_question = False
            st.rerun()
    
    def _handle_realtime_answer(self, question_id: str):
        """Handle real-time answer via WebSocket"""
        try:
            from .websocket_client import get_websocket_client, ensure_websocket_connection
            
            # Ensure WebSocket connection
            if ensure_websocket_connection():
                # WebSocket is active, add a placeholder for streaming
                self.add_streaming_message("", is_complete=False)
                
                # WebSocket will handle the streaming via background processing
                self.logger.info(f"WebSocket handling real-time answer for question {question_id}")
                
                # Set up timeout fallback
                import threading
                import time
                
                def fallback_polling():
                    time.sleep(10)  # Wait 10 seconds for WebSocket
                    if not self._is_answer_complete(question_id):
                        self.logger.info("WebSocket timeout, falling back to polling")
                        self._poll_for_answer(question_id, "")
                
                # Start fallback in background
                fallback_thread = threading.Thread(target=fallback_polling)
                fallback_thread.daemon = True
                fallback_thread.start()
            else:
                # Fall back to polling if WebSocket unavailable
                self.logger.warning("WebSocket unavailable, using polling")
                self._poll_for_answer(question_id, "")
                
        except ImportError:
            # Fall back to polling if WebSocket client not available
            self.logger.warning("WebSocket client not available, using polling")
            self._poll_for_answer(question_id, "")
    
    def _poll_for_answer(self, question_id: str, question: str):
        """Poll for answer with improved user feedback"""
        import requests
        import time
        
        try:
            max_attempts = 15  # 30 seconds total
            
            for attempt in range(max_attempts):
                time.sleep(2)
                
                response = requests.get(
                    f"{self.api_base_url}/questions/{question_id}/answer",
                    timeout=10
                )
                
                if response.status_code == 200:
                    answer_data = response.json()
                    
                    # Add complete assistant message
                    assistant_message = {
                        'type': 'assistant',
                        'content': answer_data['answer'],
                        'timestamp': datetime.now().strftime("%H:%M:%S"),
                        'sources': answer_data.get('sources', []),
                        'confidence_score': answer_data.get('confidence_score'),
                        'complete': True
                    }
                    st.session_state.chat_history.append(assistant_message)
                    return
                
                elif response.status_code == 202:
                    # Still processing - update progress if available
                    continue
                
                elif response.status_code == 404:
                    continue  # Question not found yet
            
            # Timeout
            self._add_error_message("Timeout: A resposta está demorando mais que o esperado. Tente novamente.")
            
        except Exception as e:
            self.logger.error(f"Failed to get answer: {e}")
            self._add_error_message(f"Erro ao buscar resposta: {str(e)}")
    
    def add_thinking_message(self, message: str):
        """Add a thinking/processing message to chat history"""
        thinking_msg = {
            'type': 'thinking',
            'content': message,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        }
        st.session_state.chat_history.append(thinking_msg)
    
    def remove_thinking_message(self):
        """Remove the last thinking message from chat history"""
        if (st.session_state.chat_history and 
            st.session_state.chat_history[-1].get('type') == 'thinking'):
            st.session_state.chat_history.pop()
    
    def add_streaming_message(self, content: str, is_complete: bool = False):
        """Add or update a streaming message in chat history"""
        # Check if last message is a streaming assistant message
        if (st.session_state.chat_history and 
            st.session_state.chat_history[-1].get('type') == 'assistant' and
            not st.session_state.chat_history[-1].get('complete', False)):
            # Update existing streaming message
            st.session_state.chat_history[-1]['content'] = content
            if is_complete:
                st.session_state.chat_history[-1]['complete'] = True
                st.session_state.chat_history[-1]['timestamp'] = datetime.now().strftime("%H:%M:%S")
        else:
            # Add new streaming message
            streaming_msg = {
                'type': 'assistant',
                'content': content,
                'timestamp': datetime.now().strftime("%H:%M:%S") if is_complete else '',
                'complete': is_complete,
                'sources': [],
                'confidence_score': None
            }
            st.session_state.chat_history.append(streaming_msg)
    
    def _add_error_message(self, error_msg: str):
        """Add error message to chat history"""
        error_message = {
            'type': 'error',
            'content': error_msg,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        }
        st.session_state.chat_history.append(error_message)
    
    def _render_help_section(self):
        """Render help and example questions in Portuguese"""
        st.markdown("""
        ### 🔍 Exemplos de Perguntas:
        
        - **Diabetes**: "Quais são os critérios diagnósticos para diabetes tipo 2?"
        - **Hipertensão**: "Qual o tratamento recomendado para hipertensão estágio 2?"
        - **Protocolos**: "Quais protocolos PCDT estão disponíveis para doenças cardiovasculares?"
        - **Medicamentos**: "Quais são as contraindicações para uso de metformina?"
        - **Procedimentos**: "Como é feito o diagnóstico de COVID-19 segundo os protocolos?"
        
        ### 💡 Dicas para Melhores Resultados:
        - Seja específico nas suas perguntas
        - Mencione condições, medicamentos ou procedimentos específicos
        - Pergunte sobre critérios diagnósticos, diretrizes de tratamento ou contraindicações
        - O sistema funciona melhor com perguntas sobre protocolos clínicos brasileiros (PCDT)
        - Use terminologia médica quando apropriado
        
        ### 🔄 Como Funciona:
        1. **Análise**: Sua pergunta é processada e analisada
        2. **Busca**: Documentos médicos relevantes são pesquisados
        3. **Geração**: IA gera resposta baseada em protocolos oficiais
        4. **Transparência**: Fontes e pontuação de confiança são fornecidas
        
        ### ⚙️ Recursos:
        - **Tempo Real**: Respostas transmitidas via WebSocket
        - **Fontes**: Links para documentos originais
        - **Confiança**: Pontuação de confiança da resposta
        - **Histórico**: Conversa salva na sessão atual
        """)
    
    def get_connection_status(self) -> Dict[str, bool]:
        """Get current connection status"""
        return {
            'api_connected': st.session_state.get('api_connected', True),
            'websocket_connected': st.session_state.get('websocket_connected', False),
            'session_active': bool(st.session_state.get('session_id'))
        }
    
    def set_connection_status(self, status_type: str, connected: bool):
        """Update connection status"""
        st.session_state[f'{status_type}_connected'] = connected
    
    def _is_answer_complete(self, question_id: str) -> bool:
        """Check if answer is complete for given question ID"""
        # Check if last message is a complete assistant message
        if (st.session_state.chat_history and 
            st.session_state.chat_history[-1].get('type') == 'assistant' and
            st.session_state.chat_history[-1].get('complete', False)):
            return True
        return False


def render_connection_status():
    """Render connection status indicators in sidebar"""
    # Connection status in sidebar
    with st.sidebar:
        st.subheader("🔌 Status da Conexão")
        
        # API Status
        if st.session_state.get('api_connected', True):
            st.success("🟢 API Conectada")
        else:
            st.error("🔴 API Desconectada")
        
        # WebSocket Status
        if st.session_state.get('websocket_connected', False):
            st.success("🟢 WebSocket Conectado")
        else:
            st.warning("🟡 WebSocket Desconectado")
        
        # Session Status
        if st.session_state.get('session_id'):
            st.success("🟢 Sessão Ativa")
            st.caption(f"ID: {st.session_state.session_id[:8]}...")
        else:
            st.error("🔴 Sem Sessão")


def initialize_chat_session():
    """Initialize chat session state"""
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    
    if 'processing_question' not in st.session_state:
        st.session_state.processing_question = False
    
    if 'api_connected' not in st.session_state:
        st.session_state.api_connected = True
    
    if 'websocket_connected' not in st.session_state:
        st.session_state.websocket_connected = False