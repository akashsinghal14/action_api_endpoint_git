#!/bin/bash

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt --target .

# Set Python path
export PYTHONPATH="${PYTHONPATH}:."

echo "Deployment script completed"
