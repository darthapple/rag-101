#!/bin/bash
# Universal Health Check Script for RAG-101 Services
# This script can be used by different services for health checking

set -e

SERVICE_TYPE=${1:-"unknown"}
SERVICE_PORT=${2:-"8000"}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check HTTP endpoint
check_http_health() {
    local url=$1
    local timeout=${2:-5}
    
    if curl -s -f --max-time $timeout "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ HTTP health check passed${NC}"
        return 0
    else
        echo -e "${RED}❌ HTTP health check failed${NC}"
        return 1
    fi
}

# Function to check process health
check_process_health() {
    local process_name=$1
    
    if pgrep -f "$process_name" > /dev/null; then
        echo -e "${GREEN}✅ Process health check passed${NC}"
        return 0
    else
        echo -e "${RED}❌ Process not running${NC}"
        return 1
    fi
}

# Function to check Python import health
check_python_import() {
    local module_name=$1
    
    if python -c "import $module_name; print('Import successful')" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Python import check passed${NC}"
        return 0
    else
        echo -e "${RED}❌ Python import check failed${NC}"
        return 1
    fi
}

# Function to check database connection
check_database_connection() {
    local host=${MILVUS_HOST:-"localhost"}
    local port=${MILVUS_PORT:-"19530"}
    
    # Simple TCP check for Milvus
    if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$host/$port" 2>/dev/null; then
        echo -e "${GREEN}✅ Database connection check passed${NC}"
        return 0
    else
        echo -e "${RED}❌ Database connection check failed${NC}"
        return 1
    fi
}

# Function to check NATS connection
check_nats_connection() {
    local nats_url=${NATS_URL:-"nats://localhost:4222"}
    local host=$(echo $nats_url | sed -n 's/.*:\/\/\([^:]*\).*/\1/p')
    local port=$(echo $nats_url | sed -n 's/.*:\([0-9]*\).*/\1/p')
    port=${port:-4222}
    
    if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$host/$port" 2>/dev/null; then
        echo -e "${GREEN}✅ NATS connection check passed${NC}"
        return 0
    else
        echo -e "${RED}❌ NATS connection check failed${NC}"
        return 1
    fi
}

# Main health check logic
case $SERVICE_TYPE in
    "api")
        echo "🔍 API Service Health Check"
        check_http_health "http://localhost:$SERVICE_PORT/health" 10
        exit $?
        ;;
        
    "ui")
        echo "🔍 UI Service Health Check"
        check_http_health "http://localhost:$SERVICE_PORT/_stcore/health" 10
        exit $?
        ;;
        
    "worker")
        echo "🔍 Worker Service Health Check"
        
        # Check if main Python process is running
        if ! check_process_health "main.py"; then
            exit 1
        fi
        
        # Check critical imports
        if ! check_python_import "main"; then
            exit 1
        fi
        
        # Check database connection
        if ! check_database_connection; then
            exit 1
        fi
        
        # Check NATS connection
        if ! check_nats_connection; then
            exit 1
        fi
        
        echo -e "${GREEN}✅ Worker service is healthy${NC}"
        exit 0
        ;;
        
    "infrastructure")
        echo "🔍 Infrastructure Health Check"
        
        checks_passed=0
        total_checks=2
        
        echo "Checking NATS..."
        if check_nats_connection; then
            ((checks_passed++))
        fi
        
        echo "Checking Milvus..."
        if check_database_connection; then
            ((checks_passed++))
        fi
        
        if [ $checks_passed -eq $total_checks ]; then
            echo -e "${GREEN}✅ Infrastructure is healthy ($checks_passed/$total_checks)${NC}"
            exit 0
        else
            echo -e "${RED}❌ Infrastructure check failed ($checks_passed/$total_checks)${NC}"
            exit 1
        fi
        ;;
        
    *)
        echo "❓ Unknown service type: $SERVICE_TYPE"
        echo "Usage: $0 <service_type> [port]"
        echo "Service types: api, ui, worker, infrastructure"
        exit 1
        ;;
esac