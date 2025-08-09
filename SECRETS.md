# Secrets Management for RAG-101

This document outlines the secrets management strategy and security practices for the RAG-101 system.

## Overview

RAG-101 uses environment variables for configuration management and secrets handling. This approach provides flexibility while maintaining security best practices.

## Required Secrets

### API Keys

1. **GOOGLE_API_KEY** (Required)
   - **Purpose**: Google Gemini API access for embeddings and chat functionality
   - **Format**: String (varies by Google API key type)
   - **Obtain**: https://aistudio.google.com/app/apikey
   - **Security**: High priority - grants access to Google AI services

## Environment Files

### .env.rag101.example
- Template file with all configuration options documented
- Contains placeholder values and comments
- Safe to commit to version control
- Copy to `.env` and customize for your deployment

### .env
- **NEVER commit this file to version control**
- Contains actual secrets and environment-specific configuration
- Used by Docker Compose through `env_file` directive
- Automatically loaded by all services

## Setup Process

### Automated Setup
Run the setup script to create your environment configuration:

```bash
./setup-env.sh
```

This script will:
1. Copy `.env.rag101.example` to `.env`
2. Prompt for your Google API key
3. Provide deployment instructions

### Manual Setup
1. Copy the example file:
   ```bash
   cp .env.rag101.example .env
   ```

2. Edit `.env` and replace placeholder values:
   ```bash
   nano .env  # or your preferred editor
   ```

3. Set the required API key:
   ```env
   GOOGLE_API_KEY=your_actual_api_key_here
   ```

## Docker Compose Integration

### Environment Variables in Services
Each service in `docker-compose.services.yml` uses:
- `env_file: - .env` for secrets and external configuration
- `environment:` section for service-specific and infrastructure settings

### Variable Precedence
1. **Highest**: Variables in `environment:` section
2. **Medium**: Variables from `env_file` (.env)
3. **Lowest**: Default values in Dockerfiles

## Security Best Practices

### Development
- [ ] Never commit `.env` files to version control
- [ ] Use `.env.example` files with placeholder values
- [ ] Rotate API keys regularly (recommended: every 90 days)
- [ ] Use least-privilege API keys when possible
- [ ] Store backups of `.env` files securely (encrypted)

### Production Deployment
- [ ] Use Docker secrets or Kubernetes secrets for orchestrated deployments
- [ ] Consider using secret management services (AWS Secrets Manager, Azure Key Vault, etc.)
- [ ] Implement secret rotation mechanisms
- [ ] Monitor API key usage and set up alerts for unusual activity
- [ ] Use environment-specific API keys (dev/staging/prod)

### Container Security
- [ ] Services run as non-root users in containers
- [ ] Secrets are passed as environment variables, not embedded in images
- [ ] Base images are minimal and regularly updated
- [ ] Container images don't include development tools in production

## Environment Variables Reference

### Infrastructure
| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `NATS_URL` | NATS server URL | `nats://localhost:4222` | Yes |
| `MILVUS_HOST` | Milvus database host | `localhost` | Yes |
| `MILVUS_PORT` | Milvus database port | `19530` | Yes |

### AI Configuration
| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `GOOGLE_API_KEY` | Google Gemini API key | - | Yes |
| `EMBEDDING_MODEL` | Embedding model name | `text-embedding-004` | No |
| `CHAT_MODEL` | Chat model name | `gemini-pro` | No |
| `VECTOR_DIMENSION` | Vector embedding dimension | `768` | No |

### Application Settings
| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `SESSION_TTL` | Session timeout (seconds) | `3600` | No |
| `MESSAGE_TTL` | Message TTL (seconds) | `3600` | No |
| `LOG_LEVEL` | Logging level | `INFO` | No |
| `DEBUG` | Debug mode flag | `false` | No |

### Service Configuration
| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `API_HOST` | API service host | `0.0.0.0` | No |
| `API_PORT` | API service port | `8000` | No |
| `WORKERS` | FastAPI worker count | `1` | No |
| `RATE_LIMIT_REQUESTS` | Rate limit requests | `100` | No |
| `RATE_LIMIT_WINDOW` | Rate limit window (seconds) | `60` | No |

## Troubleshooting

### Common Issues

1. **"Google API key not found" error**
   - Check that `GOOGLE_API_KEY` is set in `.env`
   - Verify the API key is valid and has proper permissions
   - Ensure the API key isn't expired

2. **Environment variables not loading**
   - Verify `.env` file exists in project root
   - Check file permissions (should be readable)
   - Restart Docker services after env changes

3. **Permission denied errors**
   - Ensure `.env` file has correct permissions: `chmod 600 .env`
   - Check Docker volume permissions

### Validation Commands

```bash
# Check if .env file exists and has content
ls -la .env && head -5 .env

# Validate Docker Compose configuration
docker-compose -f docker-compose.yml -f docker-compose.services.yml config

# Test Google API key (requires API service running)
curl -H "Authorization: Bearer $(grep GOOGLE_API_KEY .env | cut -d= -f2)" \
     "https://generativelanguage.googleapis.com/v1/models"
```

## Monitoring and Alerts

### Recommended Monitoring
- API key usage and quotas
- Authentication failures
- Unusual access patterns
- Service health checks

### Log Security
- Ensure secrets are not logged in plain text
- Use structured logging with secret filtering
- Rotate logs regularly
- Secure log storage and access

## Migration and Rotation

### API Key Rotation Process
1. Generate new API key from provider
2. Test new key in staging environment
3. Update production `.env` file
4. Restart affected services
5. Monitor for any issues
6. Deactivate old API key
7. Update backup/documentation

### Environment Migration
1. Export current configuration (excluding secrets)
2. Set up new environment with fresh `.env`
3. Migrate non-sensitive settings
4. Generate new secrets for new environment
5. Test thoroughly before switching traffic

## Compliance and Auditing

### Access Logs
- Track who has access to production secrets
- Log all secret access and modifications
- Regular access reviews and cleanup

### Backup Strategy
- Encrypted backups of configuration (not secrets)
- Documented secret recovery procedures
- Test recovery procedures regularly

### Compliance Checklist
- [ ] Secrets are not stored in version control
- [ ] Access to production secrets is limited and audited
- [ ] Secrets are rotated according to policy
- [ ] Monitoring is in place for secret usage
- [ ] Incident response plan includes secret compromise scenarios