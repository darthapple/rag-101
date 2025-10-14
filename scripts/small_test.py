#!/usr/bin/env python3
"""
Submit a small test document and monitor queue states
"""
import requests
import time
import json

API_BASE = "http://localhost:8000"

def get_queue_state():
    """Get current queue state from streams endpoint"""
    try:
        response = requests.get(f"{API_BASE}/api/v1/streams/")
        if response.status_code == 200:
            data = response.json()
            workflow = data['document_workflow']
            print(f"📊 Queues: Download={workflow['downloads']}, Chunks={workflow['chunks']}, Embeddings={workflow['embeddings']}, Complete={workflow['complete']}")
            return workflow
        else:
            print(f"❌ API error: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def submit_test_document():
    """Submit a small test document"""
    # Use a small PDF that should process quickly
    test_url = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
    
    try:
        response = requests.post(
            f"{API_BASE}/api/v1/document-download",
            json=[test_url],
            timeout=30
        )
        
        if response.status_code == 200:
            print(f"✅ Document submitted: {test_url}")
            return True
        else:
            print(f"❌ Failed to submit: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Submit error: {e}")
        return False

def main():
    print("🧪 Testing completion queue display...")
    print()
    
    # Check initial state
    print("Initial state:")
    get_queue_state()
    print()
    
    # Submit test document
    print("Submitting test document...")
    if not submit_test_document():
        return
    print()
    
    # Monitor queue changes for 30 seconds
    print("Monitoring queue changes for 30 seconds:")
    for i in range(30):
        workflow = get_queue_state()
        
        # Look for completion queue activity
        if workflow and workflow.get('complete', 0) > 0:
            print(f"🎉 SUCCESS: Completion queue shows {workflow['complete']} messages!")
            print("✅ Dashboard should now display the completion queue count")
            break
            
        time.sleep(1)
        
        # Show progress
        if i % 5 == 4:  # Every 5 seconds
            print(f"   ... {i+1}s elapsed")
    
    print()
    print("Final state:")
    get_queue_state()
    print()
    print("🌐 Check the dashboard at: http://localhost:8501")

if __name__ == "__main__":
    main()