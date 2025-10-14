#!/usr/bin/env python3
"""
Comprehensive API Test Suite for RAG-101

Tests all API endpoints and validates the complete question/answer flow:
- Health checks
- Session management (CRUD operations)
- Document upload/processing
- Question submission and answer retrieval
- WebSocket real-time communication
- Error handling and edge cases

Usage:
    python test_api_comprehensive.py [--host localhost] [--port 8000]
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import uuid
import argparse

import httpx
import websockets
import pytest


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class APITestSuite:
    """Comprehensive test suite for the RAG-101 API"""
    
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.base_url = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}"
        self.test_session_id = None
        self.test_results = {}
        self.client = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.client = httpx.AsyncClient(timeout=30.0)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.aclose()
    
    def log_test_result(self, test_name: str, success: bool, details: str = None, duration: float = None):
        """Log test result"""
        status = "PASS" if success else "FAIL" 
        self.test_results[test_name] = {
            'success': success,
            'details': details,
            'duration': duration,
            'timestamp': datetime.now().isoformat()
        }
        
        log_msg = f"[{status}] {test_name}"
        if duration:
            log_msg += f" ({duration:.2f}s)"
        if details:
            log_msg += f" - {details}"
            
        if success:
            logger.info(log_msg)
        else:
            logger.error(log_msg)

    async def test_health_endpoint(self):
        """Test basic health check endpoint"""
        start_time = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/health")
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ['status', 'service', 'version', 'infrastructure']
                missing_fields = [field for field in required_fields if field not in data]
                
                if missing_fields:
                    self.log_test_result(
                        "Health Check", 
                        False, 
                        f"Missing fields: {missing_fields}",
                        duration
                    )
                else:
                    infra = data.get('infrastructure', {})
                    self.log_test_result(
                        "Health Check", 
                        True, 
                        f"Status: {data['status']}, NATS: {infra.get('nats', {}).get('connected', 'unknown')}, Milvus: {infra.get('milvus', {}).get('connected', 'unknown')}",
                        duration
                    )
                    return data
            else:
                self.log_test_result("Health Check", False, f"HTTP {response.status_code}", duration)
                
        except Exception as e:
            self.log_test_result("Health Check", False, f"Exception: {str(e)}", time.time() - start_time)
        
        return None

    async def test_root_endpoint(self):
        """Test root API information endpoint"""
        start_time = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/")
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                self.log_test_result(
                    "Root Endpoint", 
                    True, 
                    f"Version: {data.get('version', 'unknown')}",
                    duration
                )
                return data
            else:
                self.log_test_result("Root Endpoint", False, f"HTTP {response.status_code}", duration)
                
        except Exception as e:
            self.log_test_result("Root Endpoint", False, f"Exception: {str(e)}", time.time() - start_time)
        
        return None

    async def test_session_creation(self):
        """Test session creation"""
        start_time = time.time()
        try:
            # Test session creation
            session_data = {
                "nickname": "Test User API"
            }
            
            response = await self.client.post(
                f"{self.base_url}/api/v1/sessions/",
                json=session_data
            )
            duration = time.time() - start_time
            
            if response.status_code == 201:
                data = response.json()
                required_fields = ['session_id', 'nickname', 'created_at', 'is_active']
                missing_fields = [field for field in required_fields if field not in data]
                
                if missing_fields:
                    self.log_test_result(
                        "Session Creation", 
                        False, 
                        f"Missing fields: {missing_fields}",
                        duration
                    )
                else:
                    self.test_session_id = data['session_id']
                    self.log_test_result(
                        "Session Creation", 
                        True, 
                        f"Created session {self.test_session_id[:8]}... for '{data['nickname']}'",
                        duration
                    )
                    return data
            else:
                error_detail = ""
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', 'No detail provided')
                except:
                    error_detail = response.text
                
                self.log_test_result(
                    "Session Creation", 
                    False, 
                    f"HTTP {response.status_code}: {error_detail}",
                    duration
                )
                
        except Exception as e:
            self.log_test_result("Session Creation", False, f"Exception: {str(e)}", time.time() - start_time)
        
        return None

    async def test_session_retrieval(self):
        """Test session retrieval"""
        if not self.test_session_id:
            self.log_test_result("Session Retrieval", False, "No test session ID available")
            return None
            
        start_time = time.time()
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/sessions/{self.test_session_id}"
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                self.log_test_result(
                    "Session Retrieval", 
                    True, 
                    f"Retrieved session {self.test_session_id[:8]}..., active: {data.get('is_active', 'unknown')}",
                    duration
                )
                return data
            else:
                error_detail = ""
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', 'No detail provided')
                except:
                    error_detail = response.text
                
                self.log_test_result(
                    "Session Retrieval", 
                    False, 
                    f"HTTP {response.status_code}: {error_detail}",
                    duration
                )
                
        except Exception as e:
            self.log_test_result("Session Retrieval", False, f"Exception: {str(e)}", time.time() - start_time)
        
        return None

    async def test_session_validation(self):
        """Test session validation"""
        if not self.test_session_id:
            self.log_test_result("Session Validation", False, "No test session ID available")
            return None
            
        start_time = time.time()
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/sessions/{self.test_session_id}/validate"
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                is_valid = data.get('valid', False)
                self.log_test_result(
                    "Session Validation", 
                    True, 
                    f"Session {self.test_session_id[:8]}... valid: {is_valid}",
                    duration
                )
                return data
            else:
                error_detail = ""
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', 'No detail provided')
                except:
                    error_detail = response.text
                
                self.log_test_result(
                    "Session Validation", 
                    False, 
                    f"HTTP {response.status_code}: {error_detail}",
                    duration
                )
                
        except Exception as e:
            self.log_test_result("Session Validation", False, f"Exception: {str(e)}", time.time() - start_time)
        
        return None

    async def test_document_upload(self):
        """Test document URL submission"""
        start_time = time.time()
        try:
            # Test with a sample PDF URL
            test_urls = [
                "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
            ]
            
            response = await self.client.post(
                f"{self.base_url}/api/v1/document-download",
                json=test_urls
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                submitted_count = data.get('submitted', 0)
                self.log_test_result(
                    "Document Upload", 
                    True, 
                    f"Submitted {submitted_count} URL(s) for processing",
                    duration
                )
                return data
            else:
                error_detail = ""
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', 'No detail provided')
                except:
                    error_detail = response.text
                
                self.log_test_result(
                    "Document Upload", 
                    False, 
                    f"HTTP {response.status_code}: {error_detail}",
                    duration
                )
                
        except Exception as e:
            self.log_test_result("Document Upload", False, f"Exception: {str(e)}", time.time() - start_time)
        
        return None

    async def test_question_submission(self):
        """Test question submission"""
        if not self.test_session_id:
            self.log_test_result("Question Submission", False, "No test session ID available")
            return None
            
        start_time = time.time()
        try:
            question_data = {
                "question": "What is the purpose of clinical protocols?",
                "session_id": self.test_session_id
            }
            
            response = await self.client.post(
                f"{self.base_url}/api/v1/questions/",
                json=question_data
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                question_id = data.get('question_id')
                self.log_test_result(
                    "Question Submission", 
                    True, 
                    f"Question ID: {question_id}, Status: {data.get('status', 'unknown')}",
                    duration
                )
                return data
            else:
                error_detail = ""
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', 'No detail provided')
                except:
                    error_detail = response.text
                
                self.log_test_result(
                    "Question Submission", 
                    False, 
                    f"HTTP {response.status_code}: {error_detail}",
                    duration
                )
                
        except Exception as e:
            self.log_test_result("Question Submission", False, f"Exception: {str(e)}", time.time() - start_time)
        
        return None

    async def test_websocket_connection(self):
        """Test WebSocket connection and communication"""
        if not self.test_session_id:
            self.log_test_result("WebSocket Connection", False, "No test session ID available")
            return None
            
        start_time = time.time()
        try:
            ws_url = f"{self.ws_url}/api/v1/connect?session_id={self.test_session_id}"
            
            async with websockets.connect(ws_url) as websocket:
                # Test connection establishment
                try:
                    # Wait for connection confirmation
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(response)
                    
                    if data.get('type') == 'connection_established':
                        connection_id = data.get('connection_id')
                        
                        # Test ping/pong
                        ping_msg = {
                            "type": "ping",
                            "timestamp": datetime.now().isoformat()
                        }
                        await websocket.send(json.dumps(ping_msg))
                        
                        # Wait for pong
                        pong_response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        pong_data = json.loads(pong_response)
                        
                        duration = time.time() - start_time
                        
                        if pong_data.get('type') == 'pong':
                            self.log_test_result(
                                "WebSocket Connection", 
                                True, 
                                f"Connected with ID {connection_id}, ping/pong successful",
                                duration
                            )
                            return True
                        else:
                            self.log_test_result(
                                "WebSocket Connection", 
                                False, 
                                f"Expected pong, got: {pong_data}",
                                duration
                            )
                    else:
                        duration = time.time() - start_time
                        self.log_test_result(
                            "WebSocket Connection", 
                            False, 
                            f"Expected connection_established, got: {data}",
                            duration
                        )
                        
                except asyncio.TimeoutError:
                    duration = time.time() - start_time
                    self.log_test_result(
                        "WebSocket Connection", 
                        False, 
                        "Connection timeout - no response received",
                        duration
                    )
                    
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result("WebSocket Connection", False, f"Exception: {str(e)}", duration)
        
        return None

    async def test_websocket_answer_delivery(self):
        """Test WebSocket answer delivery after question submission"""
        if not self.test_session_id:
            self.log_test_result("WebSocket Answer Delivery", False, "No test session ID available")
            return None
            
        start_time = time.time()
        try:
            ws_url = f"{self.ws_url}/api/v1/connect?session_id={self.test_session_id}"
            
            async with websockets.connect(ws_url) as websocket:
                # Wait for connection confirmation
                await asyncio.wait_for(websocket.recv(), timeout=5.0)
                
                # Submit a question via HTTP API
                question_data = {
                    "question": "Tell me about medical protocols in Brazil.",
                    "session_id": self.test_session_id
                }
                
                question_response = await self.client.post(
                    f"{self.base_url}/api/v1/questions/",
                    json=question_data
                )
                
                if question_response.status_code == 200:
                    question_result = question_response.json()
                    question_id = question_result.get('question_id')
                    
                    # Wait for answer via WebSocket (with longer timeout for AI processing)
                    try:
                        answer_received = False
                        timeout_duration = 30.0  # 30 seconds for AI processing
                        
                        while time.time() - start_time < timeout_duration:
                            try:
                                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                                data = json.loads(message)
                                
                                if data.get('type') == 'answer':
                                    answer_received = True
                                    duration = time.time() - start_time
                                    self.log_test_result(
                                        "WebSocket Answer Delivery", 
                                        True, 
                                        f"Received answer for question {question_id[:8]}... in {duration:.1f}s",
                                        duration
                                    )
                                    return data
                                    
                            except asyncio.TimeoutError:
                                # Continue waiting
                                continue
                        
                        if not answer_received:
                            duration = time.time() - start_time
                            self.log_test_result(
                                "WebSocket Answer Delivery", 
                                False, 
                                f"No answer received within {timeout_duration}s timeout",
                                duration
                            )
                        
                    except Exception as ws_e:
                        duration = time.time() - start_time
                        self.log_test_result(
                            "WebSocket Answer Delivery", 
                            False, 
                            f"WebSocket error: {str(ws_e)}",
                            duration
                        )
                        
                else:
                    duration = time.time() - start_time
                    self.log_test_result(
                        "WebSocket Answer Delivery", 
                        False, 
                        f"Question submission failed: HTTP {question_response.status_code}",
                        duration
                    )
                    
        except Exception as e:
            duration = time.time() - start_time
            self.log_test_result("WebSocket Answer Delivery", False, f"Exception: {str(e)}", duration)
        
        return None

    async def test_session_cleanup(self):
        """Test session deletion/cleanup"""
        if not self.test_session_id:
            self.log_test_result("Session Cleanup", False, "No test session ID available")
            return None
            
        start_time = time.time()
        try:
            response = await self.client.delete(
                f"{self.base_url}/api/v1/sessions/{self.test_session_id}"
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                self.log_test_result(
                    "Session Cleanup", 
                    True, 
                    f"Deleted session {self.test_session_id[:8]}...",
                    duration
                )
                
                # Verify session is actually deleted
                verify_response = await self.client.get(
                    f"{self.base_url}/api/v1/sessions/{self.test_session_id}"
                )
                
                if verify_response.status_code == 404:
                    self.log_test_result(
                        "Session Cleanup Verification", 
                        True, 
                        "Session successfully deleted (404 as expected)",
                        duration
                    )
                else:
                    self.log_test_result(
                        "Session Cleanup Verification", 
                        False, 
                        f"Session still exists after deletion: HTTP {verify_response.status_code}",
                        duration
                    )
                
                return data
            else:
                error_detail = ""
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', 'No detail provided')
                except:
                    error_detail = response.text
                
                self.log_test_result(
                    "Session Cleanup", 
                    False, 
                    f"HTTP {response.status_code}: {error_detail}",
                    duration
                )
                
        except Exception as e:
            self.log_test_result("Session Cleanup", False, f"Exception: {str(e)}", time.time() - start_time)
        
        return None

    async def run_all_tests(self):
        """Run all API tests in sequence"""
        logger.info("Starting comprehensive API test suite...")
        logger.info(f"Testing API at: {self.base_url}")
        logger.info(f"Testing WebSocket at: {self.ws_url}")
        logger.info("-" * 80)
        
        # Run tests in logical order
        test_sequence = [
            ("Infrastructure Tests", [
                self.test_health_endpoint,
                self.test_root_endpoint
            ]),
            ("Session Management Tests", [
                self.test_session_creation,
                self.test_session_retrieval,
                self.test_session_validation
            ]),
            ("Document Processing Tests", [
                self.test_document_upload
            ]),
            ("Question/Answer Flow Tests", [
                self.test_question_submission,
                self.test_websocket_connection,
                self.test_websocket_answer_delivery
            ]),
            ("Cleanup Tests", [
                self.test_session_cleanup
            ])
        ]
        
        total_tests = 0
        passed_tests = 0
        
        for category_name, test_methods in test_sequence:
            logger.info(f"\n📋 {category_name}")
            logger.info("=" * 60)
            
            for test_method in test_methods:
                total_tests += 1
                await test_method()
                
                # Check if last test passed
                test_name = test_method.__name__.replace('test_', '').replace('_', ' ').title()
                if self.test_results.get(test_name, {}).get('success', False):
                    passed_tests += 1
        
        # Print summary
        logger.info("\n" + "=" * 80)
        logger.info("🏁 TEST SUMMARY")
        logger.info("=" * 80)
        
        success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"Passed: {passed_tests}")
        logger.info(f"Failed: {total_tests - passed_tests}")
        logger.info(f"Success Rate: {success_rate:.1f}%")
        
        # Print detailed results
        logger.info("\n📊 DETAILED RESULTS:")
        logger.info("-" * 80)
        
        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result['success'] else "❌ FAIL"
            duration = f" ({result['duration']:.2f}s)" if result['duration'] else ""
            details = f" - {result['details']}" if result['details'] else ""
            logger.info(f"{status} {test_name}{duration}{details}")
        
        return {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'failed_tests': total_tests - passed_tests,
            'success_rate': success_rate,
            'results': self.test_results
        }


async def main():
    """Main function to run the test suite"""
    parser = argparse.ArgumentParser(description='Comprehensive API Test Suite for RAG-101')
    parser.add_argument('--host', default='localhost', help='API host (default: localhost)')
    parser.add_argument('--port', type=int, default=8000, help='API port (default: 8000)')
    parser.add_argument('--output', help='Output file for test results (JSON format)')
    
    args = parser.parse_args()
    
    async with APITestSuite(host=args.host, port=args.port) as test_suite:
        try:
            results = await test_suite.run_all_tests()
            
            # Save results to file if specified
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(results, f, indent=2)
                logger.info(f"\n💾 Results saved to: {args.output}")
            
            # Exit with appropriate code
            if results['success_rate'] == 100.0:
                logger.info("\n🎉 ALL TESTS PASSED!")
                sys.exit(0)
            else:
                logger.error(f"\n⚠️  {results['failed_tests']} TEST(S) FAILED")
                sys.exit(1)
                
        except KeyboardInterrupt:
            logger.info("\n🛑 Test suite interrupted by user")
            sys.exit(130)
        except Exception as e:
            logger.error(f"\n💥 Test suite crashed: {str(e)}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())