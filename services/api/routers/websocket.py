"""
WebSocket Router

Handles WebSocket connections for real-time answer delivery including:
- WebSocket connection establishment
- Session-based authentication
- Real-time message routing
"""

import logging
import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException, status
from fastapi.responses import HTMLResponse

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.websocket_manager import get_websocket_manager, WebSocketConnectionError, AuthenticationError


router = APIRouter()
logger = logging.getLogger("api.websocket")


@router.websocket("/connect")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: Optional[str] = Query(None, description="Session ID for authentication")
):
    """
    WebSocket endpoint for real-time answer delivery
    
    Args:
        websocket: WebSocket connection
        session_id: Optional session ID for authentication
    """
    connection_id = None
    websocket_manager = get_websocket_manager()
    
    try:
        # Accept WebSocket connection
        await websocket.accept()
        logger.info(f"WebSocket connection accepted from {websocket.client}")
        
        # Register connection with WebSocket manager
        try:
            connection_id = await websocket_manager.register_connection(
                websocket=websocket,
                session_id=session_id
            )
            logger.info(f"Registered WebSocket connection {connection_id}")
        except WebSocketConnectionError as e:
            logger.error(f"Failed to register WebSocket connection: {e}")
            await websocket.send_json({
                "type": "error",
                "error": "connection_registration_failed",
                "message": str(e)
            })
            await websocket.close(code=1011, reason="Registration failed")
            return
        
        # Send connection confirmation
        await websocket.send_json({
            "type": "connection_established",
            "connection_id": connection_id,
            "session_id": session_id,
            "timestamp": "2024-01-01T00:00:00Z"  # Would use actual timestamp
        })
        
        # Handle authentication if session_id not provided initially
        if not session_id:
            logger.info(f"Waiting for authentication from connection {connection_id}")
            await websocket.send_json({
                "type": "authentication_required",
                "message": "Please provide session_id to authenticate"
            })
        
        # Main message handling loop
        while True:
            try:
                # Receive message from client
                data = await websocket.receive_text()
                
                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "error": "invalid_json",
                        "message": "Message must be valid JSON"
                    })
                    continue
                
                # Handle different message types
                await handle_websocket_message(websocket, connection_id, message, websocket_manager)
                
            except WebSocketDisconnect:
                logger.info(f"WebSocket connection {connection_id} disconnected by client")
                break
                
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "error": "message_handling_failed",
                        "message": str(e)
                    })
                except:
                    # Connection might be broken
                    break
    
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    
    finally:
        # Clean up connection
        if connection_id:
            try:
                await websocket_manager.unregister_connection(connection_id)
                logger.info(f"Unregistered WebSocket connection {connection_id}")
            except Exception as e:
                logger.error(f"Error unregistering connection {connection_id}: {e}")


async def handle_websocket_message(
    websocket: WebSocket,
    connection_id: str,
    message: Dict[str, Any],
    websocket_manager
):
    """
    Handle incoming WebSocket messages
    
    Args:
        websocket: WebSocket connection
        connection_id: Connection identifier
        message: Parsed message data
        websocket_manager: WebSocket manager instance
    """
    message_type = message.get("type")
    
    if message_type == "authenticate":
        # Handle session authentication
        session_id = message.get("session_id")
        if not session_id:
            await websocket.send_json({
                "type": "authentication_error",
                "error": "missing_session_id",
                "message": "session_id is required for authentication"
            })
            return
        
        # Authenticate with session ID
        success = await websocket_manager.authenticate_connection(connection_id, session_id)
        
        if success:
            await websocket.send_json({
                "type": "authentication_success",
                "session_id": session_id,
                "message": "Successfully authenticated"
            })
            logger.info(f"Authenticated connection {connection_id} with session {session_id}")
        else:
            await websocket.send_json({
                "type": "authentication_error",
                "error": "authentication_failed",
                "message": "Session authentication failed"
            })
    
    elif message_type == "ping":
        # Handle ping messages
        await websocket.send_json({
            "type": "pong",
            "timestamp": message.get("timestamp", "2024-01-01T00:00:00Z")
        })
    
    elif message_type == "subscribe":
        # Handle topic subscriptions (for future features)
        topics = message.get("topics", [])
        await websocket.send_json({
            "type": "subscription_confirmed",
            "topics": topics,
            "message": f"Subscribed to {len(topics)} topics"
        })
    
    elif message_type == "get_status":
        # Handle status requests
        connection_info = websocket_manager.get_connection_info(connection_id)
        if connection_info:
            await websocket.send_json({
                "type": "status_response",
                "connection_info": connection_info
            })
        else:
            await websocket.send_json({
                "type": "error",
                "error": "connection_not_found",
                "message": "Connection information not available"
            })
    
    else:
        # Unknown message type
        await websocket.send_json({
            "type": "error",
            "error": "unknown_message_type",
            "message": f"Unknown message type: {message_type}"
        })


@router.get("/test-client")
async def websocket_test_client():
    """
    Simple HTML test client for WebSocket connections
    (Only available in development)
    """
    from shared.config import get_config
    config = get_config()
    
    if config.is_production():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test client not available in production"
        )
    
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>RAG WebSocket Test Client</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .container { max-width: 800px; margin: 0 auto; }
            .messages { 
                border: 1px solid #ccc; 
                height: 300px; 
                padding: 10px; 
                overflow-y: scroll; 
                background: #f9f9f9; 
                margin: 10px 0;
            }
            .input-group { margin: 10px 0; }
            .input-group input, .input-group button { 
                padding: 5px; 
                margin: 5px; 
            }
            .message { 
                margin: 5px 0; 
                padding: 5px; 
                border-left: 3px solid #007cba;
                background: white;
            }
            .error { border-left-color: #d32f2f; }
            .success { border-left-color: #2e7d32; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>RAG WebSocket Test Client</h1>
            
            <div class="input-group">
                <input type="text" id="sessionId" placeholder="Session ID (optional)" />
                <button onclick="connect()">Connect</button>
                <button onclick="disconnect()">Disconnect</button>
                <span id="status">Disconnected</span>
            </div>
            
            <div class="messages" id="messages"></div>
            
            <div class="input-group">
                <input type="text" id="messageInput" placeholder="Type a message..." />
                <button onclick="sendMessage()">Send</button>
                <button onclick="authenticate()">Authenticate</button>
                <button onclick="ping()">Ping</button>
                <button onclick="getStatus()">Get Status</button>
            </div>
            
            <div class="input-group">
                <button onclick="clearMessages()">Clear Messages</button>
            </div>
        </div>

        <script>
            let ws = null;
            const messages = document.getElementById('messages');
            const status = document.getElementById('status');
            
            function addMessage(content, type = 'info') {
                const div = document.createElement('div');
                div.className = `message ${type}`;
                div.innerHTML = `<strong>${new Date().toLocaleTimeString()}</strong>: ${content}`;
                messages.appendChild(div);
                messages.scrollTop = messages.scrollHeight;
            }
            
            function connect() {
                const sessionId = document.getElementById('sessionId').value;
                const wsUrl = sessionId 
                    ? `ws://localhost:8000/ws/connect?session_id=${sessionId}`
                    : `ws://localhost:8000/ws/connect`;
                
                ws = new WebSocket(wsUrl);
                
                ws.onopen = function(event) {
                    status.textContent = 'Connected';
                    status.style.color = 'green';
                    addMessage('WebSocket connected', 'success');
                };
                
                ws.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    addMessage(`Received: ${JSON.stringify(data, null, 2)}`);
                };
                
                ws.onclose = function(event) {
                    status.textContent = 'Disconnected';
                    status.style.color = 'red';
                    addMessage(`WebSocket closed (code: ${event.code})`, 'error');
                };
                
                ws.onerror = function(error) {
                    addMessage(`WebSocket error: ${error}`, 'error');
                };
            }
            
            function disconnect() {
                if (ws) {
                    ws.close();
                    ws = null;
                }
            }
            
            function sendMessage() {
                const input = document.getElementById('messageInput');
                if (ws && input.value) {
                    try {
                        const message = JSON.parse(input.value);
                        ws.send(JSON.stringify(message));
                        addMessage(`Sent: ${input.value}`, 'success');
                        input.value = '';
                    } catch (e) {
                        addMessage(`Invalid JSON: ${e.message}`, 'error');
                    }
                }
            }
            
            function authenticate() {
                const sessionId = document.getElementById('sessionId').value || 'test-session-123';
                if (ws) {
                    const message = {
                        type: 'authenticate',
                        session_id: sessionId
                    };
                    ws.send(JSON.stringify(message));
                    addMessage(`Sent authentication for session: ${sessionId}`, 'success');
                }
            }
            
            function ping() {
                if (ws) {
                    const message = {
                        type: 'ping',
                        timestamp: new Date().toISOString()
                    };
                    ws.send(JSON.stringify(message));
                    addMessage('Sent ping', 'success');
                }
            }
            
            function getStatus() {
                if (ws) {
                    const message = { type: 'get_status' };
                    ws.send(JSON.stringify(message));
                    addMessage('Requested status', 'success');
                }
            }
            
            function clearMessages() {
                messages.innerHTML = '';
            }
            
            // Handle Enter key in message input
            document.getElementById('messageInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)


@router.get("/connections")
async def list_websocket_connections():
    """
    List active WebSocket connections (for monitoring)
    
    Returns:
        Dict[str, Any]: Connection statistics
    """
    try:
        websocket_manager = get_websocket_manager()
        stats = websocket_manager.get_stats()
        
        return {
            "total_connections": stats.get('active_connections', 0),
            "total_sessions": stats.get('active_sessions', 0),
            "connections_created": stats.get('connections_created', 0),
            "connections_closed": stats.get('connections_closed', 0),
            "messages_sent": stats.get('messages_sent', 0),
            "messages_failed": stats.get('messages_failed', 0),
            "nats_connected": stats.get('nats_connected', False),
            "manager_running": stats.get('manager_running', False)
        }
        
    except Exception as e:
        logger.error(f"Failed to get WebSocket connections: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Connection listing failed: {str(e)}"
        )