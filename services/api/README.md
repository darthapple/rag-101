# RAG-101 API Service

FastAPI service for the RAG-101 medical Q&A system providing REST endpoints and WebSocket connections for real-time answer delivery.

## Features

- **Session Management**: Create and manage Q&A sessions with TTL-based expiration
- **Document Processing**: Upload PDF documents for processing and indexing
- **Q&A Interactions**: Submit questions and receive AI-generated answers
- **WebSocket Support**: Real-time answer delivery via WebSocket connections
- **Health Monitoring**: Health checks, metrics, and service status endpoints

## Architecture

- **FastAPI**: Modern async web framework with automatic API documentation
- **WebSocket Manager**: Real-time connection management and message routing
- **NATS Integration**: Message-driven architecture for scalable processing
- **Pydantic Models**: Request/response validation and serialization
- **Structured Logging**: Comprehensive logging for monitoring and debugging

## API Endpoints

### Health & Monitoring
- `GET /health` - Service health check
- `GET /health/ready` - Readiness check for load balancers
- `GET /health/metrics` - Prometheus-compatible metrics
- `GET /health/version` - Version information

### Sessions
- `POST /api/v1/sessions` - Create new session
- `GET /api/v1/sessions/{session_id}` - Get session details
- `PUT /api/v1/sessions/{session_id}/metadata` - Update session metadata
- `DELETE /api/v1/sessions/{session_id}` - Delete session
- `POST /api/v1/sessions/{session_id}/validate` - Validate session

### Documents
- `POST /api/v1/documents/upload` - Upload PDF document
- `GET /api/v1/documents/jobs/{job_id}/status` - Get processing status
- `GET /api/v1/documents` - List documents with pagination
- `DELETE /api/v1/documents/jobs/{job_id}` - Cancel processing job
- `GET /api/v1/documents/stats` - Processing statistics

### Questions
- `POST /api/v1/questions` - Submit question
- `GET /api/v1/questions/{question_id}/status` - Get question status
- `GET /api/v1/questions/{question_id}/answer` - Get generated answer
- `GET /api/v1/questions/sessions/{session_id}/history` - Question history
- `GET /api/v1/questions/stats` - Question statistics

### WebSocket
- `WS /ws/connect` - WebSocket connection endpoint
- `GET /ws/test-client` - WebSocket test client (development only)
- `GET /ws/connections` - List active connections

## Development Setup

### Prerequisites
- Python 3.11+
- Poetry for dependency management
- Docker (optional, for containerization)

### Local Development

1. **Install dependencies**:
   ```bash
   cd services/api
   poetry install
   poetry shell
   ```

2. **Set environment variables**:
   ```bash
   export GOOGLE_API_KEY=your_api_key_here
   export NATS_URL=nats://localhost:4222
   export ENVIRONMENT=development
   ```

3. **Run the service**:
   ```bash
   poetry run uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Access the API**:
   - OpenAPI docs: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc
   - Health check: http://localhost:8000/health
   - WebSocket test: http://localhost:8000/ws/test-client

### Docker Development

1. **Build the image**:
   ```bash
   docker build -t rag-api:latest .
   ```

2. **Run with Docker**:
   ```bash
   docker run -p 8000:8000 \
     -e GOOGLE_API_KEY=your_key \
     -e NATS_URL=nats://host.docker.internal:4222 \
     rag-api:latest
   ```

## Configuration

The service uses environment variables for configuration:

### Core Settings
- `ENVIRONMENT` - Deployment environment (development/production)
- `API_HOST` - Server host (default: 0.0.0.0)
- `API_PORT` - Server port (default: 8000)
- `DEBUG` - Enable debug mode (default: false)
- `LOG_LEVEL` - Logging level (default: INFO)

### External Services
- `NATS_URL` - NATS server URL (default: nats://localhost:4222)
- `GOOGLE_API_KEY` - Google Gemini API key (required)

### WebSocket Settings
- `MAX_WEBSOCKET_CONNECTIONS` - Maximum concurrent connections (default: 100)
- `MAX_CONNECTIONS_PER_SESSION` - Max connections per session (default: 5)
- `WEBSOCKET_HEARTBEAT_INTERVAL` - Heartbeat interval in seconds (default: 30)

### Request Limits
- `MAX_REQUEST_SIZE` - Maximum request size in bytes (default: 16MB)
- `REQUEST_TIMEOUT` - Request timeout in seconds (default: 30)
- `MAX_FILE_SIZE` - Maximum upload file size in bytes (default: 50MB)

### CORS
- `CORS_ORIGINS` - Allowed CORS origins (default: ["*"])
- `CORS_METHODS` - Allowed CORS methods (default: ["GET", "POST", "PUT", "DELETE"])

## Testing

Run tests with pytest:

```bash
poetry run pytest
poetry run pytest --cov=api --cov=routers  # With coverage
poetry run pytest -m unit                  # Unit tests only
poetry run pytest -m integration           # Integration tests only
```

## Code Quality

The project uses several tools for code quality:

```bash
poetry run black .          # Code formatting
poetry run ruff check .     # Linting
poetry run mypy .           # Type checking
```

## Monitoring

### Health Checks
- `/health` - Basic health status
- `/health/ready` - Kubernetes readiness probe
- `/health/metrics` - Prometheus metrics

### Metrics Available
- `rag_api_websocket_connections_total` - Active WebSocket connections
- `rag_api_websocket_sessions_total` - Active sessions
- `rag_api_websocket_messages_sent_total` - Messages sent via WebSocket
- `rag_api_websocket_messages_failed_total` - Failed message deliveries
- `rag_api_nats_connected` - NATS connection status

### Logging
- Structured JSON logging in production
- Request/response logging with correlation IDs
- Error tracking with stack traces
- Performance metrics with processing times

## Production Deployment

### Docker Compose
The service integrates with the main docker-compose configuration:

```yaml
services:
  api:
    build: ./services/api
    ports:
      - "8000:8000"
    environment:
      - GOOGLE_API_KEY=${GOOGLE_API_KEY}
      - NATS_URL=nats://nats:4222
      - ENVIRONMENT=production
    depends_on:
      - nats
```

### Health Checks
The container includes health checks for monitoring:
- HTTP health endpoint check every 30 seconds
- 30-second timeout with 3 retries
- 5-second startup grace period

### Security
- Runs as non-root user (apiuser)
- Minimal attack surface with slim base image
- No dev dependencies in production image
- Trusted host middleware in production

## Integration with RAG System

The API service integrates with other RAG system components:

1. **Worker Service**: Processes documents and questions via NATS messaging
2. **NATS JetStream**: Message broker for ephemeral data processing
3. **Milvus**: Vector database for similarity search (accessed via Worker)
4. **WebSocket Manager**: Real-time answer delivery to connected clients
5. **UI Service**: Frontend application consuming the API endpoints

## Error Handling

The API includes comprehensive error handling:

- **Validation Errors**: Pydantic model validation with detailed error messages
- **HTTP Exceptions**: Proper HTTP status codes and error responses
- **Global Exception Handler**: Catches and logs unhandled exceptions
- **Request Correlation**: Unique request IDs for error tracking
- **Timeout Handling**: Request timeouts with appropriate error responses

## WebSocket Protocol

WebSocket connections support the following message types:

### Client -> Server
```json
{"type": "authenticate", "session_id": "session-123"}
{"type": "ping", "timestamp": "2024-01-01T00:00:00Z"}
{"type": "subscribe", "topics": ["answers"]}
{"type": "get_status"}
```

### Server -> Client
```json
{"type": "connection_established", "connection_id": "conn-123"}
{"type": "authentication_success", "session_id": "session-123"}
{"type": "answer", "question_id": "q-123", "answer": "...", "sources": [...]}
{"type": "pong", "timestamp": "2024-01-01T00:00:00Z"}
{"type": "error", "error": "error_code", "message": "Error description"}
```

## Performance Considerations

- **Async/Await**: Full async support for concurrent request handling
- **Connection Pooling**: Efficient WebSocket connection management
- **Memory Usage**: Bounded connection limits and cleanup routines
- **Request Timeouts**: Configurable timeouts prevent resource exhaustion
- **Graceful Shutdown**: Proper cleanup during container restarts

For more details on the overall RAG system architecture, see the main project documentation.