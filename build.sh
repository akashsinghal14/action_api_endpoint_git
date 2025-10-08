#!/bin/bash
echo "=== Azure Build Script ==="
echo "Installing Python dependencies..."

# Install dependencies
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "Build completed!"
