#!/bin/bash
# Build the MATLAB base image for MUR processing modules
#
# This script checks if the base image exists and builds it if needed.
# Can be called manually or automatically by module build scripts.

set -e

# Configuration
BASE_IMAGE_NAME="mur-matlab-base"
BASE_IMAGE_TAG="r2024b"
BASE_IMAGE_FULL="${BASE_IMAGE_NAME}:${BASE_IMAGE_TAG}"
BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MATLAB_BASE_DIR="${BUILD_DIR}/matlab-base"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "MUR MATLAB Base Image Builder"
echo "========================================"
echo "Image: ${BASE_IMAGE_FULL}"
echo ""

# Check if image already exists
if docker image inspect "${BASE_IMAGE_FULL}" >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Base image ${BASE_IMAGE_FULL} already exists"

    # Check if force rebuild requested
    if [ "$1" == "--force" ] || [ "$1" == "-f" ]; then
        echo -e "${YELLOW}⚠${NC}  Force rebuild requested"
    else
        echo ""
        echo "To rebuild the base image:"
        echo "  $0 --force"
        exit 0
    fi
fi

# Check if network.lic exists
if [ ! -f "${BUILD_DIR}/network.lic" ]; then
    echo -e "${RED}✗${NC} network.lic not found"
    echo ""
    echo "Please create network.lic from template:"
    echo "  cd ${BUILD_DIR}"
    echo "  cp network.lic.example network.lic"
    echo "  # Edit network.lic with your license server details"
    exit 1
fi

echo -e "${YELLOW}→${NC} Building MATLAB base image..."
echo ""
echo "This will:"
echo "  1. Download MATLAB R2024b runtime (~2GB)"
echo "  2. Install runtime and dependencies"
echo "  3. Create base image (~3.5GB)"
echo ""
echo "This may take 10-20 minutes on first build."
echo ""

# Build the base image
cd "${MATLAB_BASE_DIR}"
docker build \
    --platform linux/amd64 \
    -t "${BASE_IMAGE_FULL}" \
    -f Dockerfile \
    ..

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓${NC} Successfully built ${BASE_IMAGE_FULL}"
    echo ""
    echo "Base image is now available for module builds."
else
    echo ""
    echo -e "${RED}✗${NC} Failed to build base image"
    exit 1
fi
