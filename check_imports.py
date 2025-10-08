#!/usr/bin/env python3
"""
Test script to check if all required modules are available
"""
import sys

print("Python version:", sys.version)
print("Python path:", sys.path)

modules_to_test = [
    'flask',
    'flask_cors', 
    'openai',
    'anthropic',
    'dotenv',
    'json',
    're',
    'datetime',
    'typing',
    'os'
]

print("\nTesting module imports:")
for module in modules_to_test:
    try:
        __import__(module)
        print(f"✅ {module} - OK")
    except ImportError as e:
        print(f"❌ {module} - FAILED: {e}")

print("\nTest completed!")
