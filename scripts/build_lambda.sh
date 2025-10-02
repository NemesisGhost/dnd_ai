#!/bin/bash

# Build script for Lambda deployment package with dependencies
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/lambda_build"
ZIP_FILE="$SCRIPT_DIR/db_init_lambda.zip"

# Clean up previous build
rm -rf "$BUILD_DIR"
rm -f "$ZIP_FILE"

# Create build directory
mkdir -p "$BUILD_DIR"

# Copy Python files
cp "$SCRIPT_DIR/db_init_lambda.py" "$BUILD_DIR/index.py"

# Install dependencies
pip install -r "$SCRIPT_DIR/requirements.txt" -t "$BUILD_DIR"

# Create zip file
cd "$BUILD_DIR"
zip -r "$ZIP_FILE" .

# Clean up build directory
cd "$SCRIPT_DIR"
rm -rf "$BUILD_DIR"

echo "Lambda deployment package created: $ZIP_FILE"