#!/bin/bash
# Build script for Render.com deployment
# This script installs Tesseract and Python dependencies

set -e

echo "Installing Tesseract OCR..."
apt-get update
apt-get install -y tesseract-ocr tesseract-ocr-spa

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Build completed successfully!"
