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
    
    def _render_connection_status(self):
        """Render connection status indicators"""
        # Update WebSocket status from client before displaying
        from .websocket_client import update_websocket_status
        update_websocket_status()
        
        status_col1, status_col2, status_col3 = st.columns(3)
        
        with status_col1:
            if st.session_state.get('api_connected', True):
                st.success("🟢 API Conectada")
            else:
                st.error("🔴 API Desconectada")
        
        with status_col2:
            # Check WebSocket status with connecting state
            if st.session_state.get('websocket_connected', False):
                st.success("🟢 WebSocket Ativo")
            elif st.session_state.get('websocket_connecting', False):
                # Show animated spinner while connecting
                with st.spinner("WebSocket Conectando..."):
                    st.info("⏳ Estabelecendo conexão...")
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
        for idx, message in enumerate(st.session_state.chat_history):
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
                    # Check if this message should use typing effect
                    # Ensure message has an ID for tracking typing state
                    if 'id' not in message:
                        message['id'] = f"msg_{idx}"
                    
                    message_id = message.get('id', f"msg_{len(st.session_state.chat_history)}")
                    is_complete = message.get('complete', True)
                    typing_active = st.session_state.get(f"typing_active_{message_id}", False)
                    
                    # Simplified typing effect logic
                    # Show typing effect for messages that are marked for typing (including empty content for loading)
                    if typing_active and not message.get('typing_complete', False):
                        self._render_message_with_typing(content, message_id)
                        # Check if typing is complete (only for non-empty content)
                        if content:
                            typing_index = st.session_state.get(f"typing_index_{message_id}", 0)
                            if typing_index >= len(content):
                                message['typing_complete'] = True
                                st.session_state[f"typing_active_{message_id}"] = False
                    elif content:
                        # Show complete message immediately (no typing effect needed)
                        st.write(content)
                    # If no content and not typing active, show nothing (avoid empty message)
                    
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
        # Show warning if WebSocket is still connecting
        ws_connected = st.session_state.get('websocket_connected', False)
        ws_connecting = st.session_state.get('websocket_connecting', False)
        
        if ws_connecting and not ws_connected:
            st.warning("⏳ **Aguarde:** WebSocket está conectando... O chat estará disponível em instantes.")
        elif not ws_connected and not ws_connecting:
            st.info("💡 **Dica:** WebSocket desconectado. As respostas podem demorar mais usando modo de consulta alternativo.")
        
        # Chat input at the bottom - disable if processing or WebSocket connecting
        input_disabled = st.session_state.get('processing_question', False) or (ws_connecting and not ws_connected)
        
        question = st.chat_input(
            placeholder="Digite sua pergunta sobre protocolos médicos..." if not input_disabled else "Aguarde a conexão...",
            key="chat_input",
            disabled=input_disabled
        )
        
        # Simple clear chat button (advanced options removed)
        col1, col2 = st.columns([4, 1])
        with col2:
            if st.button("🗑️ Limpar Chat", type="secondary"):
                st.session_state.chat_history = []
                if 'processing_question' in st.session_state:
                    del st.session_state.processing_question
                st.rerun()
        
        # Set default values for removed options
        priority = "normal"
        use_websocket = True
        
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
            
            # Add processing message with better feedback
            self.add_thinking_message("🤔 Analisando sua pergunta...")
            
            # Submit question to API
            payload = {
                "question": question,
                "session_id": self.session_id
            }
            
            headers = {
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                f"{self.api_base_url}/api/v1/questions/",
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
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
                # WebSocket is active, add a placeholder for streaming with animated loading
                self.add_streaming_message("", is_complete=False)
                
                # Remove thinking message since we now have streaming placeholder
                self.remove_thinking_message()
                
                # WebSocket will handle the streaming via background processing
                self.logger.info(f"WebSocket handling real-time answer for question {question_id}")
                
                # Note: Fallback polling disabled since WebSocket should work reliably now
                # If WebSocket fails, the user can retry the question
            else:
                # Update thinking message for polling mode
                self.update_thinking_message("📞 WebSocket indisponível, consultando via API...")
                
                # Fall back to polling if WebSocket unavailable
                self.logger.warning("WebSocket unavailable, using polling")
                self._poll_for_answer(question_id, "")
                
        except ImportError:
            # Update thinking message for polling mode
            self.update_thinking_message("📞 Usando modo de consulta direta...")
            
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
                # Update thinking message with progress
                progress = f"🔄 Consultando resposta... ({attempt + 1}/{max_attempts})"
                self.update_thinking_message(progress)
                
                time.sleep(2)
                
                response = requests.get(
                    f"{self.api_base_url}/questions/{question_id}/answer",
                    timeout=10
                )
                
                if response.status_code == 200:
                    answer_data = response.json()
                    
                    # Add complete assistant message (check if session state exists)
                    try:
                        assistant_message = {
                            'type': 'assistant',
                            'content': answer_data['answer'],
                            'timestamp': datetime.now().strftime("%H:%M:%S"),
                            'sources': answer_data.get('sources', []),
                            'confidence_score': answer_data.get('confidence_score'),
                            'complete': True
                        }
                        
                        # Only add to session state if we have access to it
                        if hasattr(st.session_state, 'chat_history'):
                            st.session_state.chat_history.append(assistant_message)
                        else:
                            self.logger.warning("Cannot access session state from background thread")
                    except Exception as se:
                        self.logger.warning(f"Session state access failed: {se}")
                    return
                
                elif response.status_code == 202:
                    # Still processing - update progress if available
                    continue
                
                elif response.status_code == 404:
                    continue  # Question not found yet
            
            # Timeout - try to add error message safely
            try:
                self._add_error_message("Timeout: A resposta está demorando mais que o esperado. Tente novamente.")
            except Exception as se:
                self.logger.error(f"Cannot add error message from background thread: {se}")
            
        except Exception as e:
            self.logger.error(f"Failed to get answer: {e}")
            try:
                self._add_error_message(f"Erro ao buscar resposta: {str(e)}")
            except Exception as se:
                self.logger.error(f"Cannot add error message from background thread: {se}")
    
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
    
    def update_thinking_message(self, message: str):
        """Update the last thinking message or add new one"""
        if (st.session_state.chat_history and 
            st.session_state.chat_history[-1].get('type') == 'thinking'):
            # Update existing thinking message
            st.session_state.chat_history[-1]['content'] = message
            st.session_state.chat_history[-1]['timestamp'] = datetime.now().strftime("%H:%M:%S")
        else:
            # Add new thinking message
            self.add_thinking_message(message)
    
    def add_streaming_message(self, content: str, is_complete: bool = False):
        """Add or update a streaming message in chat history"""
        # Check if last message is a streaming assistant message
        if (st.session_state.chat_history and 
            st.session_state.chat_history[-1].get('type') == 'assistant' and
            not st.session_state.chat_history[-1].get('complete', False)):
            # Update existing streaming message
            message = st.session_state.chat_history[-1]
            message['content'] = content
            if is_complete:
                message['complete'] = True
                message['timestamp'] = datetime.now().strftime("%H:%M:%S")
                message['typing_complete'] = False  # Enable typing effect
                # Start typing effect for this message
                message_id = message.get('id', f"msg_{len(st.session_state.chat_history)-1}")
                if content:  # Only start typing effect if there's content
                    self.start_typing_effect(message_id, content)
        else:
            # Add new streaming message
            message_id = f"msg_{len(st.session_state.chat_history)}"
            streaming_msg = {
                'id': message_id,
                'type': 'assistant',
                'content': content,
                'timestamp': datetime.now().strftime("%H:%M:%S") if is_complete else '',
                'complete': is_complete,
                'sources': [],
                'confidence_score': None,
                'typing_complete': False  # Always enable typing effect to show loading/typing
            }
            st.session_state.chat_history.append(streaming_msg)
            
            # Always start typing effect for streaming messages (even empty ones show spinner)
            self.start_typing_effect(message_id, content)
    
    def update_streaming_message(self, content: str, sources: list = None, confidence_score: float = None, is_complete: bool = True):
        """Update the current streaming message with complete data"""
        if (st.session_state.chat_history and 
            st.session_state.chat_history[-1].get('type') == 'assistant' and
            not st.session_state.chat_history[-1].get('complete', False)):
            # Update existing streaming message with complete data
            message = st.session_state.chat_history[-1]
            message['content'] = content
            message['complete'] = is_complete
            message['timestamp'] = datetime.now().strftime("%H:%M:%S")
            message['typing_complete'] = False  # Enable typing effect
            if sources:
                message['sources'] = sources
            if confidence_score is not None:
                message['confidence_score'] = confidence_score
            
            # Start typing effect for updated message
            message_id = message.get('id', f"msg_{len(st.session_state.chat_history)-1}")
            if content:  # Start typing effect for any content
                self.start_typing_effect(message_id, content)
        else:
            # No streaming message exists, add complete message
            message_id = f"msg_{len(st.session_state.chat_history)}"
            assistant_message = {
                'id': message_id,
                'type': 'assistant',
                'content': content,
                'timestamp': datetime.now().strftime("%H:%M:%S"),
                'sources': sources or [],
                'confidence_score': confidence_score,
                'complete': True,
                'typing_complete': False  # Enable typing effect
            }
            st.session_state.chat_history.append(assistant_message)
            
            # Start typing effect for new complete message
            if content:
                self.start_typing_effect(message_id, content)
    
    def _get_websocket_status(self) -> bool:
        """Get current WebSocket connection status"""
        try:
            from .websocket_client import get_websocket_client
            
            if not hasattr(st.session_state, 'config') or not hasattr(st.session_state, 'session_id'):
                return False
            
            ws_client = get_websocket_client(st.session_state.config, st.session_state.session_id)
            return ws_client.connected if ws_client else False
        except:
            return False
    
    def _add_error_message(self, error_msg: str):
        """Add error message to chat history"""
        error_message = {
            'type': 'error',
            'content': error_msg,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        }
        st.session_state.chat_history.append(error_message)
    
    def render_typing_message(self, content: str, message_key: str = "typing_msg") -> None:
        """Render a message with typing effect using a configurable delay"""
        typing_delay = self.config.get('typing_delay_ms', 100) / 1000  # Convert to seconds
        
        # Create placeholder for the message
        if f"typing_placeholder_{message_key}" not in st.session_state:
            st.session_state[f"typing_placeholder_{message_key}"] = st.empty()
        
        placeholder = st.session_state[f"typing_placeholder_{message_key}"]
        
        # Initialize typing state
        if f"typing_index_{message_key}" not in st.session_state:
            st.session_state[f"typing_index_{message_key}"] = 0
        
        current_index = st.session_state[f"typing_index_{message_key}"]
        
        # Display content up to current index with spinner if not complete
        if current_index < len(content):
            partial_content = content[:current_index + 1]
            
            # Show spinner alongside the typing text
            with placeholder.container():
                col1, col2 = st.columns([1, 20])
                with col1:
                    if current_index < len(content) - 1:
                        st.spinner("")  # Show spinner while typing
                with col2:
                    st.markdown(partial_content)
            
            # Update index for next render
            st.session_state[f"typing_index_{message_key}"] = current_index + 1
            
            # Auto-refresh to continue typing
            time.sleep(typing_delay)
            st.rerun()
        else:
            # Typing complete - show final content without spinner
            with placeholder.container():
                st.markdown(content)
            
            # Clean up typing state
            if f"typing_index_{message_key}" in st.session_state:
                del st.session_state[f"typing_index_{message_key}"]
    
    def start_typing_effect(self, message_id: str, content: str) -> None:
        """Start typing effect for a message"""
        # Initialize typing state for this message
        st.session_state[f"typing_active_{message_id}"] = True
        st.session_state[f"typing_content_{message_id}"] = content
        st.session_state[f"typing_index_{message_id}"] = 0
    
    def _render_animated_spinner(self, spinner_key: str = "default") -> str:
        """Render animated loading dots"""
        # Initialize spinner state
        if f"spinner_frame_{spinner_key}" not in st.session_state:
            st.session_state[f"spinner_frame_{spinner_key}"] = 0
            st.session_state[f"spinner_last_update_{spinner_key}"] = time.time()
        
        current_time = time.time()
        last_update = st.session_state[f"spinner_last_update_{spinner_key}"]
        frame = st.session_state[f"spinner_frame_{spinner_key}"]
        
        # Update animation frame every 200ms
        if current_time - last_update >= 0.2:
            st.session_state[f"spinner_frame_{spinner_key}"] = (frame + 1) % 4
            st.session_state[f"spinner_last_update_{spinner_key}"] = current_time
            frame = st.session_state[f"spinner_frame_{spinner_key}"]
        
        # Create animated dots pattern
        dots = ["●", "●", "●"]
        for i in range(3):
            if (frame + i) % 4 == 0:
                dots[i] = "○"  # Empty dot
        
        return " ".join(dots)
    
    def _render_message_with_typing(self, content: str, message_id: str) -> None:
        """Render message with typing effect and animated spinner"""
        if not content:
            # Show only animated loading spinner when no content yet
            spinner_text = self._render_animated_spinner(message_id)
            st.markdown(f"**{spinner_text}**")
            # Schedule rerun to continue animation
            time.sleep(0.1)
            st.rerun()
            return
            
        # Initialize typing state if not exists - be more defensive
        typing_index_key = f"typing_index_{message_id}"
        typing_time_key = f"typing_last_update_{message_id}"
        
        if typing_index_key not in st.session_state:
            st.session_state[typing_index_key] = 0
        if typing_time_key not in st.session_state:
            st.session_state[typing_time_key] = time.time()
        
        current_index = st.session_state.get(typing_index_key, 0)
        last_update = st.session_state.get(typing_time_key, time.time())
        typing_delay = self.config.get('typing_delay_ms', 50) / 1000  # Convert to seconds
        
        # Check if typing is complete
        if current_index >= len(content):
            # Typing complete - show full content
            st.write(content)
            # Clean up typing state - be more careful
            keys_to_delete = [k for k in st.session_state.keys() if k.startswith(f"typing_") and message_id in k]
            keys_to_delete.extend([k for k in st.session_state.keys() if k.startswith(f"spinner_") and message_id in k])
            for key in keys_to_delete:
                try:
                    del st.session_state[key]
                except KeyError:
                    pass  # Key already deleted
            return
        
        # Check if enough time has passed for next character
        current_time = time.time()
        if current_time - last_update >= typing_delay:
            # Time to show next character
            new_index = min(current_index + 1, len(content))
            st.session_state[typing_index_key] = new_index
            st.session_state[typing_time_key] = current_time
            current_index = new_index
        
        # Show content up to current index
        partial_content = content[:current_index] if current_index > 0 else ""
        
        # Only show spinner if no content has been typed yet
        if current_index == 0:
            # Show only animated spinner when no typing has started
            spinner_text = self._render_animated_spinner(message_id)
            st.markdown(f"**{spinner_text}**")
        else:
            # Show only the typed content (no spinner once typing starts)
            st.write(partial_content)
        
        # Schedule rerun if still typing
        if current_index < len(content):
            time.sleep(0.01)  # Minimal delay to prevent excessive CPU usage
            st.rerun()
    
    
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
    # Update WebSocket status before displaying
    from .websocket_client import update_websocket_status
    update_websocket_status()
    
    # Connection status in sidebar
    with st.sidebar:
        st.subheader("🔌 Status da Conexão")
        
        # API Status
        if st.session_state.get('api_connected', True):
            st.success("🟢 API Conectada")
        else:
            st.error("🔴 API Desconectada")
        
        # WebSocket Status (consistent with chat header)
        if st.session_state.get('websocket_connected', False):
            st.success("🟢 WebSocket Ativo")
        elif st.session_state.get('websocket_connecting', False):
            st.info("🔄 WebSocket Conectando...")
        else:
            st.warning("🟡 WebSocket Inativo")
        
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