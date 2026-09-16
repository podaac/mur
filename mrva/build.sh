#!/bin/bash
# Build script for MRVA container
#
# Usage: ./build.sh [--no-cache] [--platform PLATFORM]
#
# Examples:
#   ./build.sh                           # Standard build
#   ./build.sh --no-cache                # Force rebuild all layers
#   ./build.sh --platform linux/amd64    # Specific platform (for Apple Silicon)

set -e

# Parse arguments
NO_CACHE=""
PLATFORM="linux/amd64"

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache)
            NO_CACHE="--no-cache"
            shift
            ;;
        --platform)
            PLATFORM="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--no-cache] [--platform PLATFORM]"
            exit 1
            ;;
    esac
done

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MUR_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================="
echo "MRVA Container Build"
echo "========================================="
echo "Build context: $MUR_DIR"
echo "Dockerfile:    $SCRIPT_DIR/Dockerfile"
echo "Platform:      $PLATFORM"
echo "Cache:         ${NO_CACHE:-enabled}"
echo "========================================="
echo ""

# Change to MUR directory (parent of mrva)
cd "$MUR_DIR"

# Build the container
echo "Starting Docker build..."
docker build \
    $NO_CACHE \
    --platform "$PLATFORM" \
    -t mrva:latest \
    -f mrva/Dockerfile \
    .

# Check if build was successful
if [ $? -eq 0 ]; then
    echo ""
    echo "========================================="
    echo "Build completed successfully!"
    echo "========================================="
    echo "Image: mrva:latest"
    echo ""
    echo "Image size:"
    docker images mrva:latest --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}"
    echo ""
    echo "To test the container, run:"
    echo "  cd $SCRIPT_DIR"
    echo "  ./test_container.sh"
    echo ""
else
    echo ""
    echo "========================================="
    echo "Build failed!"
    echo "========================================="
    exit 1
fi
