#!/bin/bash
# Wait for Services Script
# This script waits for all required services to be healthy before starting application services

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
TIMEOUT=300  # 5 minutes default timeout
INTERVAL=5   # Check every 5 seconds

# Usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  -t, --timeout SECONDS   Maximum time to wait (default: 300)"
    echo "  -i, --interval SECONDS  Check interval (default: 5)"
    echo "  -h, --help             Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  NATS_URL               NATS server URL (default: nats://localhost:4222)"
    echo "  MILVUS_HOST            Milvus host (default: localhost)"
    echo "  MILVUS_PORT            Milvus port (default: 19530)"
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        -i|--interval)
            INTERVAL="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Set default values from environment or use defaults
NATS_URL=${NATS_URL:-"nats://localhost:4222"}
MILVUS_HOST=${MILVUS_HOST:-"localhost"}
MILVUS_PORT=${MILVUS_PORT:-"19530"}

# Extract NATS host and port
NATS_HOST=$(echo $NATS_URL | sed -n 's/.*:\/\/\([^:]*\).*/\1/p')
NATS_PORT=$(echo $NATS_URL | sed -n 's/.*:\([0-9]*\).*/\1/p')
NATS_PORT=${NATS_PORT:-4222}

echo -e "${BLUE}🔍 Waiting for services to be ready...${NC}"
echo "Timeout: ${TIMEOUT}s, Check interval: ${INTERVAL}s"
echo ""

# Function to check if a TCP port is open
check_tcp() {
    local host=$1
    local port=$2
    local service_name=$3
    
    if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$host/$port"; then
        echo -e "${GREEN}✅ $service_name is ready ($host:$port)${NC}"
        return 0
    else
        echo -e "${YELLOW}⏳ Waiting for $service_name ($host:$port)...${NC}"
        return 1
    fi
}

# Function to check HTTP endpoint
check_http() {
    local url=$1
    local service_name=$2
    
    if curl -s -f "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ $service_name is ready ($url)${NC}"
        return 0
    else
        echo -e "${YELLOW}⏳ Waiting for $service_name ($url)...${NC}"
        return 1
    fi
}

# Function to check NATS JetStream
check_nats_jetstream() {
    local host=$1
    local port=$2
    
    # First check if NATS is listening
    if ! check_tcp "$host" "$port" "NATS TCP"; then
        return 1
    fi
    
    # Check if JetStream is enabled (this is a simple check)
    # In a real scenario, you might want to use NATS CLI tools
    echo -e "${GREEN}✅ NATS JetStream is assumed ready${NC}"
    return 0
}

# Function to check Milvus health
check_milvus_health() {
    local host=$1
    local port=$2
    
    # Check if Milvus API port is open
    if check_tcp "$host" "$port" "Milvus API"; then
        # Check health endpoint if available
        if check_http "http://$host:9091/healthz" "Milvus Health"; then
            return 0
        fi
        # If health endpoint isn't available, assume ready if port is open
        echo -e "${GREEN}✅ Milvus is ready (port check passed)${NC}"
        return 0
    fi
    return 1
}

# Main waiting loop
start_time=$(date +%s)
all_ready=false

echo -e "${BLUE}📋 Checking required services:${NC}"
echo "1. NATS JetStream at $NATS_HOST:$NATS_PORT"
echo "2. Milvus at $MILVUS_HOST:$MILVUS_PORT"
echo ""

while [ $all_ready = false ]; do
    current_time=$(date +%s)
    elapsed=$((current_time - start_time))
    
    if [ $elapsed -ge $TIMEOUT ]; then
        echo -e "${RED}❌ Timeout reached (${TIMEOUT}s). Services are not ready.${NC}"
        echo "Please check:"
        echo "1. Docker services are running: docker-compose ps"
        echo "2. Network connectivity"
        echo "3. Service logs: docker-compose logs"
        exit 1
    fi
    
    echo -e "${BLUE}⏱️  Checking services... (${elapsed}s elapsed)${NC}"
    
    # Check all services
    nats_ready=false
    milvus_ready=false
    
    if check_nats_jetstream "$NATS_HOST" "$NATS_PORT"; then
        nats_ready=true
    fi
    
    if check_milvus_health "$MILVUS_HOST" "$MILVUS_PORT"; then
        milvus_ready=true
    fi
    
    if [ "$nats_ready" = true ] && [ "$milvus_ready" = true ]; then
        all_ready=true
        echo ""
        echo -e "${GREEN}🎉 All services are ready!${NC}"
        echo "Total wait time: ${elapsed}s"
        break
    fi
    
    echo ""
    sleep $INTERVAL
done

echo ""
echo -e "${GREEN}✅ Services are ready. You can now start the application services.${NC}"
echo ""
echo "Next steps:"
echo "1. Start application services:"
echo "   ${GREEN}docker-compose -f docker-compose.yml -f docker-compose.services.yml up --build${NC}"
echo ""
echo "2. Or run individual services locally:"
echo "   ${GREEN}cd services/worker && poetry run python main.py${NC}"
echo "   ${GREEN}cd services/api && poetry run uvicorn main:app --reload${NC}"
echo "   ${GREEN}cd services/ui && poetry run streamlit run main.py${NC}"