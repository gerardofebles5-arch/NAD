#!/bin/bash

# Copy modules to cloud_functions directory for deployment
# Usage: ./copy_modules_to_cloud_functions.sh

set -e

echo "📦 Copying modules to cloud_functions directory..."

# Create directories
mkdir -p cloud_functions/billing
mkdir -p cloud_functions/ocr
mkdir -p cloud_functions/core
mkdir -p cloud_functions/utils
mkdir -p cloud_functions/drive
mkdir -p cloud_functions/schemas

# Copy billing modules
echo "📋 Copying billing modules..."
cp billing/*.py cloud_functions/billing/

# Copy OCR modules
echo "📋 Copying OCR modules..."
cp ocr/*.py cloud_functions/ocr/

# Copy core modules
echo "📋 Copying core modules..."
cp core/*.py cloud_functions/core/

# Copy utils modules
echo "📋 Copying utils modules..."
cp utils/*.py cloud_functions/utils/

# Copy drive modules
echo "📋 Copying drive modules..."
cp drive/*.py cloud_functions/drive/

# Copy schemas
echo "📋 Copying schemas..."
cp schemas/*.py cloud_functions/schemas/

# Copy __init__.py files
echo "📋 Copying __init__.py files..."
cp billing/__init__.py cloud_functions/billing/
cp ocr/__init__.py cloud_functions/ocr/
cp core/__init__.py cloud_functions/core/
cp utils/__init__.py cloud_functions/utils/
cp drive/__init__.py cloud_functions/drive/

echo "✅ Modules copied successfully!"
echo "📝 Ready to deploy to Google Cloud Functions"
