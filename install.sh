#!/bin/bash

echo "🔍 Checking for NVIDIA GPU..."

# Detect NVIDIA GPU
if lspci | grep -i nvidia > /dev/null 2>&1; then
    echo "✅ NVIDIA GPU detected."

    echo "📦 Installing dependencies..."
    if command -v pip >/dev/null 2>&1; then
        pip install -r requirements.txt
    elif command -v pip3 >/dev/null 2>&1; then
        pip3 install -r requirements.txt
    else
        echo "❌ pip not found. Please install Python and pip first."
        exit 1
    fi

    echo "✅ Installation complete."
else
    echo "❌ You are not using an NVIDIA GPU!"
    exit 1
fi
