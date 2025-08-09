#!/bin/bash
# RAG-101 Environment Setup Script
# This script helps set up the environment configuration for RAG-101

set -e

echo "🔧 RAG-101 Environment Setup"
echo "============================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if .env already exists
if [ -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file already exists!${NC}"
    read -p "Do you want to overwrite it? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}ℹ️  Keeping existing .env file. You can manually compare with .env.rag101.example${NC}"
        exit 0
    fi
fi

# Copy the RAG-101 template
echo -e "${BLUE}📄 Creating .env from RAG-101 template...${NC}"
cp .env.rag101.example .env

echo -e "${GREEN}✅ Environment file created!${NC}"
echo ""

# Prompt for required API key
echo -e "${YELLOW}🔑 Required Configuration${NC}"
echo "You need to set up your Google Gemini API key for RAG-101 to work."
echo ""
echo "1. Visit: https://aistudio.google.com/app/apikey"
echo "2. Create a new API key"
echo "3. Copy the API key"
echo ""

read -p "Do you want to enter your Google API key now? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Enter your Google API key: " -s GOOGLE_KEY
    echo
    if [ ! -z "$GOOGLE_KEY" ]; then
        # Replace the placeholder in .env file
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            sed -i '' "s/your_google_gemini_api_key_here/$GOOGLE_KEY/" .env
        else
            # Linux
            sed -i "s/your_google_gemini_api_key_here/$GOOGLE_KEY/" .env
        fi
        echo -e "${GREEN}✅ Google API key configured!${NC}"
    else
        echo -e "${YELLOW}⚠️  No API key entered. You'll need to edit .env manually.${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Don't forget to edit .env and add your Google API key!${NC}"
fi

echo ""
echo -e "${BLUE}🐳 Docker Setup${NC}"
echo "To run RAG-101 with Docker:"
echo ""
echo "1. Start infrastructure services:"
echo "   ${GREEN}docker-compose up -d${NC}"
echo ""
echo "2. Start application services:"
echo "   ${GREEN}docker-compose -f docker-compose.yml -f docker-compose.services.yml up --build${NC}"
echo ""
echo "3. Access the application:"
echo "   • UI: http://localhost:8501"
echo "   • API: http://localhost:8000"
echo "   • API Docs: http://localhost:8000/docs"
echo ""

echo -e "${BLUE}🔧 Development Setup${NC}"
echo "For local development:"
echo ""
echo "1. Start infrastructure only:"
echo "   ${GREEN}docker-compose up -d${NC}"
echo ""
echo "2. Run services locally:"
echo "   ${GREEN}cd services/worker && poetry run python main.py${NC}"
echo "   ${GREEN}cd services/api && poetry run uvicorn main:app --reload${NC}"
echo "   ${GREEN}cd services/ui && poetry run streamlit run main.py${NC}"
echo ""

echo -e "${GREEN}🎉 Setup complete!${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Review and customize .env file as needed"
echo "2. Ensure Docker is running"
echo "3. Run the Docker setup commands above"
echo ""
echo "For more information, see README.md and CLAUDE.md"