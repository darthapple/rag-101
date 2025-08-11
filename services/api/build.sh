#!/bin/bash

# Build script for API service with shared module

set -e

echo "Building RAG-101 API Docker image..."

# Create a temporary build directory
BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

# Copy API service files
cp -r . "$BUILD_DIR/"

# Copy shared module
cp -r ../../shared "$BUILD_DIR/shared"

# Build the Docker image
cd "$BUILD_DIR"
docker build -t rag-101-api:latest .

echo "Docker image built successfully: rag-101-api:latest"