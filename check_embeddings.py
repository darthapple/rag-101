#!/usr/bin/env python3
"""Check if embeddings are saved in Milvus and display sample data"""

import asyncio
from pymilvus import connections, Collection
import json
from datetime import datetime

async def check_milvus():
    try:
        # Connect to Milvus
        connections.connect('default', host='localhost', port='19530')
        
        # Get collection
        collection = Collection('medical_documents')
        
        # Load collection to memory
        collection.load()
        
        # Get collection stats
        print(f'Collection: {collection.name}')
        print(f'Number of entities: {collection.num_entities}')
        print(f'Schema fields: {[field.name for field in collection.schema.fields]}')
        
        if collection.num_entities > 0:
            # Query to get one row with all fields
            results = collection.query(
                expr='chunk_id != ""',  # Get all records
                output_fields=['*'],  # Get all fields
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
                    # Show first 1000 characters
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
                    
                    # Calculate some stats
                    import numpy as np
                    arr = np.array(embedding)
                    print(f'  • Min value: {arr.min():.6f}')
                    print(f'  • Max value: {arr.max():.6f}')
                    print(f'  • Mean value: {arr.mean():.6f}')
                    print(f'  • Std deviation: {arr.std():.6f}')
                
                print('\n' + '='*80)
                
                # Show more samples if requested
                print(f'\n📊 COLLECTION STATISTICS:')
                print(f'  • Total chunks in database: {collection.num_entities}')
                
                # Get unique documents
                unique_docs = collection.query(
                    expr='chunk_id != ""',
                    output_fields=['document_title', 'source_url'],
                    limit=1000
                )
                unique_titles = set(doc.get('document_title', '') for doc in unique_docs if doc.get('document_title'))
                print(f'  • Unique documents: {len(unique_titles)}')
                
                if unique_titles:
                    print('\n📚 INDEXED DOCUMENTS:')
                    for i, title in enumerate(unique_titles, 1):
                        print(f'  {i}. {title}')
                        
        else:
            print('\n⚠️ No documents found in collection')
            print('Please upload and process some documents first.')
    
    except Exception as e:
        print(f'❌ Error connecting to Milvus: {e}')
        print('Make sure Milvus is running (docker compose up)')
    
    finally:
        # Disconnect
        if connections.list_connections()[0]:
            connections.disconnect('default')

if __name__ == '__main__':
    asyncio.run(check_milvus())