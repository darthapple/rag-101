# RAG-101 Worker Service Dockerfile
# Multi-stage build for optimized production image

# Build stage
FROM python:3.11-slim as builder

# Install system dependencies for building
# Configure proxy if provided via build args
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && unset http_proxy https_proxy no_proxy

# Install Poetry
RUN pip install poetry==1.7.1

# Configure Poetry  
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_CACHE_DIR=/opt/poetry-cache

# Set working directory
WORKDIR /app

# Copy Poetry configuration files
COPY services/worker/pyproject.toml services/worker/poetry.lock ./

# Install dependencies
RUN poetry install --only=main --no-root && rm -rf $POETRY_CACHE_DIR

# Production stage
FROM python:3.11-slim as production

# Install runtime system dependencies
# Configure proxy if provided via build args
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

RUN apt-get update && apt-get install -y \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && unset http_proxy https_proxy no_proxy

# Create non-root user
RUN groupadd -r worker && useradd -r -g worker -d /app -s /sbin/nologin worker

# Set working directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy project root shared modules (required for imports)
COPY --chown=worker:worker shared /app/shared

# Copy application code
COPY --chown=worker:worker services/worker /app/services/worker

# Ensure health check script is executable
RUN chmod +x /app/services/worker/health_check.py || true

# Set working directory to worker service
WORKDIR /app/services/worker

# Make sure virtual environment is in PATH
ENV PATH="/app/.venv/bin:$PATH"

# Create directories for logs and runtime data
RUN mkdir -p /app/logs /app/runtime && chown -R worker:worker /app

# Switch to non-root user
USER worker

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import asyncio; from main import WorkerService; print('healthy')" || exit 1

# Environment variables
ENV PYTHONPATH="/app:/app/services/worker:$PYTHONPATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose metrics port (if implemented)
EXPOSE 8080

# Default command
CMD ["python", "-m", "main"]

# Labels for metadata
LABEL maintainer="RAG-101 Team" \
      service="worker" \
      version="0.1.0" \
      description="Background processing service for RAG-101 medical Q&A system"