"""
Session Manager Component

Handles session creation and management for the Streamlit UI.
Communicates with the FastAPI service to create and manage user sessions.
"""

import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime


class SessionManager:
    """Manages user sessions for the Streamlit UI"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize session manager with configuration"""
        self.config = config
        self.api_base_url = config['api_base_url']
        self.session_ttl = config['session_ttl']
        self.logger = logging.getLogger("ui.session_manager")
    
    def create_session(self, nickname: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Create a new session with the API service
        
        Args:
            nickname: Optional user nickname
            
        Returns:
            Dict containing session data or None if failed
        """
        try:
            # Prepare request payload
            payload = {
                "nickname": nickname or "Anonymous User",
                "ttl": self.session_ttl
            }
            
            # Make request to API service
            response = requests.post(
                f"{self.api_base_url}/sessions",
                json=payload,
                timeout=10
            )
            
            if response.status_code == 201:
                session_data = response.json()
                self.logger.info(f"Created session: {session_data['session_id']}")
                return session_data
            else:
                self.logger.error(f"Session creation failed: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to create session: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error creating session: {e}")
            return None
    
    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session information from API service
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dict containing session info or None if failed
        """
        try:
            response = requests.get(
                f"{self.api_base_url}/sessions/{session_id}",
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                self.logger.error(f"Failed to get session info: {response.status_code}")
                return None
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to get session info: {e}")
            return None
    
    def validate_session(self, session_id: str) -> bool:
        """
        Validate that a session is still active
        
        Args:
            session_id: Session identifier
            
        Returns:
            bool: True if session is valid
        """
        try:
            response = requests.get(
                f"{self.api_base_url}/sessions/{session_id}",
                timeout=5
            )
            
            return response.status_code == 200
            
        except requests.exceptions.RequestException:
            return False
    
    def extend_session(self, session_id: str, additional_ttl: int = None) -> bool:
        """
        Extend session TTL
        
        Args:
            session_id: Session identifier
            additional_ttl: Additional time to add (seconds)
            
        Returns:
            bool: True if extension successful
        """
        try:
            payload = {
                "ttl": additional_ttl or self.session_ttl
            }
            
            response = requests.patch(
                f"{self.api_base_url}/sessions/{session_id}",
                json=payload,
                timeout=10
            )
            
            return response.status_code == 200
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to extend session: {e}")
            return False