#!/bin/bash

# PDF Digital Signer - Run Script for Linux/macOS

echo "Starting PDF Digital Signer..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Check if dependencies are installed
python3 -c "import PyQt5" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# Run the application
python3 main.py
