#!/bin/bash
# Simple script to check Milvus database contents
# Runs using the worker's Poetry environment

cd services/worker && poetry run python -c "
import sys
sys.path.append('../..')
exec(open('../../check_embeddings.py').read())
"