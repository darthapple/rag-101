#!/bin/bash
# RAG-101 Deployment Script
# Comprehensive deployment orchestration with health checks and dependency management

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="docker-compose.yml"
SERVICES_FILE="docker-compose.services.yml"
TIMEOUT=300
ENVIRONMENT="production"

# Usage information
usage() {
    echo -e "${BOLD}RAG-101 Deployment Script${NC}"
    echo ""
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo -e "${BOLD}Commands:${NC}"
    echo "  up                  Start all services (default)"
    echo "  down                Stop all services"
    echo "  restart             Restart all services"
    echo "  infrastructure      Start only infrastructure services"
    echo "  services           Start only application services"
    echo "  logs               Show logs for all services"
    echo "  status             Show service status"
    echo "  health             Check service health"
    echo "  clean              Clean up all resources"
    echo ""
    echo -e "${BOLD}Options:${NC}"
    echo "  -t, --timeout SEC  Health check timeout (default: 300)"
    echo "  -e, --env ENV      Environment (development|production, default: production)"
    echo "  -d, --detach       Run in detached mode"
    echo "  -f, --force        Force rebuild images"
    echo "  -h, --help         Show this help message"
    echo ""
    echo -e "${BOLD}Examples:${NC}"
    echo "  $0 up -d           Start all services in background"
    echo "  $0 services        Start only application services"
    echo "  $0 logs api        Show logs for API service"
    echo "  $0 health          Check health of all services"
    exit 0
}

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_header() {
    echo -e "\n${BOLD}${BLUE}🚀 $1${NC}\n"
}

# Check prerequisites
check_prerequisites() {
    log_header "Checking Prerequisites"
    
    # Check if Docker is running
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
    log_success "Docker is running"
    
    # Check if Docker Compose is available
    if ! command -v docker-compose > /dev/null; then
        log_error "Docker Compose is not installed"
        exit 1
    fi
    log_success "Docker Compose is available"
    
    # Check if .env file exists
    if [ ! -f .env ]; then
        log_warning ".env file not found"
        if [ -f .env.rag101.example ]; then
            log_info "Creating .env from template..."
            cp .env.rag101.example .env
            log_warning "Please edit .env file and add your Google API key"
            log_info "Run: nano .env"
            exit 1
        else
            log_error "No .env template found. Please run ./setup-env.sh first"
            exit 1
        fi
    fi
    log_success "Environment configuration found"
    
    # Check if Google API key is set
    if grep -q "your_google_gemini_api_key_here" .env 2>/dev/null; then
        log_warning "Google API key not configured in .env file"
        log_info "Please edit .env and set GOOGLE_API_KEY"
        exit 1
    fi
    log_success "Configuration appears complete"
}

# Infrastructure services management
start_infrastructure() {
    log_header "Starting Infrastructure Services"
    
    docker-compose up -d etcd minio standalone nats
    
    log_info "Waiting for infrastructure services to be healthy..."
    if ./scripts/wait-for-services.sh -t $TIMEOUT; then
        log_success "Infrastructure services are ready"
    else
        log_error "Infrastructure services failed to start"
        docker-compose logs
        exit 1
    fi
}

# Application services management
start_services() {
    local force_rebuild=$1
    local detached=$2
    
    log_header "Starting Application Services"
    
    # Build arguments
    build_args=""
    if [ "$force_rebuild" = true ]; then
        build_args="--build --force-recreate"
    fi
    
    # Run arguments
    run_args=""
    if [ "$detached" = true ]; then
        run_args="-d"
    fi
    
    # Set target based on environment
    target="production"
    if [ "$ENVIRONMENT" = "development" ]; then
        target="development"
    fi
    
    # Start application services
    docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE up $build_args $run_args
}

# Stop all services
stop_services() {
    log_header "Stopping All Services"
    
    # Stop application services first
    if docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE ps -q | grep -q .; then
        log_info "Stopping application services..."
        docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE down
    fi
    
    # Stop infrastructure services
    log_info "Stopping infrastructure services..."
    docker-compose down
    
    log_success "All services stopped"
}

# Show service status
show_status() {
    log_header "Service Status"
    
    echo -e "${BOLD}Infrastructure Services:${NC}"
    docker-compose ps
    echo ""
    
    echo -e "${BOLD}Application Services:${NC}"
    docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE ps
}

# Show logs
show_logs() {
    local service=$1
    
    if [ -n "$service" ]; then
        log_header "Logs for $service"
        if docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE ps -q "$service" | grep -q .; then
            docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE logs -f "$service"
        elif docker-compose ps -q "$service" | grep -q .; then
            docker-compose logs -f "$service"
        else
            log_error "Service $service not found"
            exit 1
        fi
    else
        log_header "All Service Logs"
        docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE logs -f
    fi
}

# Health checks
check_health() {
    log_header "Health Check"
    
    # Check infrastructure
    log_info "Checking infrastructure health..."
    if ./scripts/health-check.sh infrastructure; then
        log_success "Infrastructure is healthy"
    else
        log_error "Infrastructure health check failed"
        return 1
    fi
    
    # Check application services
    services=("worker" "api" "ui")
    ports=("8080" "8000" "8501")
    
    for i in "${!services[@]}"; do
        service="${services[$i]}"
        port="${ports[$i]}"
        
        log_info "Checking $service health..."
        if docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE exec -T "$service" /app/scripts/health-check.sh "$service" "$port" 2>/dev/null; then
            log_success "$service is healthy"
        else
            log_warning "$service health check failed (may not be critical)"
        fi
    done
    
    log_success "Health check completed"
}

# Clean up
clean_up() {
    log_header "Cleaning Up Resources"
    
    read -p "This will remove all containers, images, and volumes. Are you sure? (y/N): " -r
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Clean up cancelled"
        exit 0
    fi
    
    # Stop all services
    stop_services
    
    # Remove containers and networks
    log_info "Removing containers and networks..."
    docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE down --remove-orphans
    docker-compose down --remove-orphans
    
    # Remove volumes
    log_info "Removing volumes..."
    docker-compose -f $COMPOSE_FILE -f $SERVICES_FILE down -v
    docker-compose down -v
    
    # Remove images
    log_info "Removing images..."
    docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}" | grep rag101 | awk '{print $3}' | xargs -r docker rmi -f
    
    log_success "Cleanup completed"
}

# Parse command line arguments
COMMAND="up"
DETACHED=false
FORCE_REBUILD=false
SERVICE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        up|down|restart|infrastructure|services|logs|status|health|clean)
            COMMAND="$1"
            shift
            ;;
        -t|--timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        -e|--env)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -d|--detach)
            DETACHED=true
            shift
            ;;
        -f|--force)
            FORCE_REBUILD=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            if [ "$COMMAND" = "logs" ] && [ -z "$SERVICE" ]; then
                SERVICE="$1"
                shift
            else
                log_error "Unknown option: $1"
                usage
            fi
            ;;
    esac
done

# Main execution
log_header "RAG-101 Deployment - $COMMAND"

case $COMMAND in
    "up")
        check_prerequisites
        start_infrastructure
        start_services $FORCE_REBUILD $DETACHED
        
        if [ "$DETACHED" = true ]; then
            log_success "All services started in background"
            echo ""
            log_info "Access the application:"
            echo "  • UI: http://localhost:8501"
            echo "  • API: http://localhost:8000"
            echo "  • API Docs: http://localhost:8000/docs"
            echo ""
            log_info "Check status: $0 status"
            log_info "View logs: $0 logs"
            log_info "Health check: $0 health"
        fi
        ;;
        
    "down")
        stop_services
        ;;
        
    "restart")
        stop_services
        sleep 2
        start_infrastructure
        start_services $FORCE_REBUILD $DETACHED
        ;;
        
    "infrastructure")
        start_infrastructure
        ;;
        
    "services")
        start_services $FORCE_REBUILD $DETACHED
        ;;
        
    "logs")
        show_logs "$SERVICE"
        ;;
        
    "status")
        show_status
        ;;
        
    "health")
        check_health
        ;;
        
    "clean")
        clean_up
        ;;
        
    *)
        log_error "Unknown command: $COMMAND"
        usage
        ;;
esac

log_success "Command completed successfully"