#!/usr/bin/env python3
"""
Unified Milvus Database Checker
Combines features from multiple checking scripts into one comprehensive tool.

Usage:
    python scripts/check_milvus.py              # Full detailed check
    python scripts/check_milvus.py --simple     # Quick status check only
    python scripts/check_milvus.py --docker     # Run via Docker exec
"""

import argparse
import asyncio
import sys
from pymilvus import connections, Collection, utility
import json
from datetime import datetime


def connect_milvus(host='localhost', port='19530'):
    """Connect to Milvus database"""
    try:
        connections.connect('default', host=host, port=port)
        return True
    except Exception as e:
        print(f'❌ Error connecting to Milvus: {e}')
        print(f'Make sure Milvus is running at {host}:{port}')
        return False


def simple_check():
    """Quick status check - minimal output"""
    try:
        collection = Collection('medical_documents')
        collection.load()

        print(f"✅ Milvus connected")
        print(f"📊 Documents in database: {collection.num_entities}")

        if collection.num_entities > 0:
            results = collection.query(
                expr='chunk_id != ""',
                output_fields=['document_title', 'text_content'],
                limit=1
            )
            if results:
                print(f"\n📄 Sample document: {results[0].get('document_title', 'N/A')}")
                text = results[0].get('text_content', '')[:200]
                print(f"   Text preview: {text}...")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def detailed_check():
    """Comprehensive check with full statistics"""
    try:
        collection = Collection('medical_documents')
        collection.load()

        # Collection info
        print(f'Collection: {collection.name}')
        print(f'Number of entities: {collection.num_entities}')
        print(f'Schema fields: {[field.name for field in collection.schema.fields]}')

        if collection.num_entities == 0:
            print('\n⚠️ No documents found in collection')
            print('Please upload and process some documents first.')
            return True

        # Get sample document
        results = collection.query(
            expr='chunk_id != ""',
            output_fields=['*'],
            limit=1
        )

        if results:
            print('\n' + '='*80)
            print('SAMPLE DOCUMENT CHUNK')
            print('='*80)
            row = results[0]

            # Display metadata
            print('\n📋 METADATA:')
            print(f'  • Chunk ID: {row.get("chunk_id", "N/A")}')
            print(f'  • Document Title: {row.get("document_title", "N/A")}')
            print(f'  • Source URL: {row.get("source_url", "N/A")}')
            print(f'  • Page Number: {row.get("page_number", "N/A")}')
            print(f'  • Diseases: {row.get("diseases", "N/A")}')
            print(f'  • Processed At: {row.get("processed_at", "N/A")}')
            print(f'  • Job ID: {row.get("job_id", "N/A")}')

            # Display text content
            print('\n📄 TEXT CONTENT:')
            text = row.get('text_content', 'N/A')
            if text != 'N/A':
                preview = text[:1000] + '...' if len(text) > 1000 else text
                print(f'  {preview}')
                print(f'\n  [Total length: {len(text)} characters]')

            # Show embedding info
            if 'embedding' in row:
                embedding = row['embedding']
                print('\n🔢 EMBEDDING VECTOR:')
                print(f'  • Dimension: {len(embedding)}')
                print(f'  • First 10 values: {embedding[:10]}')
                print(f'  • Data type: {type(embedding[0]).__name__}')

                # Calculate stats
                import numpy as np
                arr = np.array(embedding)
                print(f'  • Min value: {arr.min():.6f}')
                print(f'  • Max value: {arr.max():.6f}')
                print(f'  • Mean value: {arr.mean():.6f}')
                print(f'  • Std deviation: {arr.std():.6f}')

            print('\n' + '='*80)

        # Collection statistics
        print(f'\n📊 COLLECTION STATISTICS:')
        print(f'  • Total chunks in database: {collection.num_entities}')

        # Get unique documents
        unique_docs = collection.query(
            expr='chunk_id != ""',
            output_fields=['document_title', 'source_url', 'job_id'],
            limit=1000
        )
        unique_titles = set(doc.get('document_title', '') for doc in unique_docs if doc.get('document_title'))
        unique_jobs = set(doc.get('job_id', '') for doc in unique_docs if doc.get('job_id'))

        print(f'  • Unique documents: {len(unique_titles)}')
        print(f'  • Unique jobs: {len(unique_jobs)}')

        if unique_titles:
            print('\n📚 INDEXED DOCUMENTS:')
            for i, title in enumerate(sorted(unique_titles), 1):
                # Count chunks for this document
                doc_chunks = sum(1 for doc in unique_docs if doc.get('document_title') == title)
                print(f'  {i}. {title} ({doc_chunks} chunks)')

        return True

    except Exception as e:
        print(f'❌ Error: {e}')
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Check Milvus database status and contents',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s                  # Full detailed check
  %(prog)s --simple         # Quick status only
  %(prog)s --host milvus    # Connect to different host
        '''
    )
    parser.add_argument('--simple', action='store_true',
                       help='Quick status check only')
    parser.add_argument('--host', default='localhost',
                       help='Milvus host (default: localhost)')
    parser.add_argument('--port', type=int, default=19530,
                       help='Milvus port (default: 19530)')

    args = parser.parse_args()

    # Connect to Milvus
    if not connect_milvus(args.host, args.port):
        sys.exit(1)

    try:
        # Run appropriate check
        if args.simple:
            success = simple_check()
        else:
            success = detailed_check()

        sys.exit(0 if success else 1)

    finally:
        # Disconnect
        if connections.list_connections():
            connections.disconnect('default')


if __name__ == '__main__':
    main()
