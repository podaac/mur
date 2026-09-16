#!/bin/bash
# Build MUR processing modules with automatic base image check
#
# Usage:
#   ./build_module.sh <module_name>                    - Build a specific module (production)
#   ./build_module.sh <module_name> --debug            - Build with debug symbols and bounds checking
#   ./build_module.sh all                              - Build all modules (production)
#   ./build_module.sh all --debug                      - Build all modules with debug enabled
#
# Debug builds enable:
#   - Debug symbols (-g) for meaningful stack traces
#   - Runtime bounds checking (-check bounds) to catch array overflows
#   - Uninitialized variable detection (-check uninit)
#   - Floating-point exception trapping (-fpe0)
#   - Full compiler warnings (-warn all)
#   - No optimization (-O0) for easier debugging

set -e

# Configuration
BASE_IMAGE_NAME="mur-matlab-base"
BASE_IMAGE_TAG="r2024b"
BASE_IMAGE_FULL="${BASE_IMAGE_NAME}:${BASE_IMAGE_TAG}"
BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Available modules
MODULES=("iquam" "l2p" "landice" "mrva")

# Build flags
DEBUG_MODE=0
NO_CACHE=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to build a single module
build_module() {
    local MODULE=$1
    local MODULE_DIR="${BUILD_DIR}/${MODULE}"

    if [ ! -d "$MODULE_DIR" ]; then
        echo -e "${RED}✗${NC} Module directory not found: $MODULE_DIR"
        return 1
    fi

    echo ""
    echo "========================================"
    echo "Building Module: ${MODULE}"
    if [ "$DEBUG_MODE" -eq 1 ]; then
        echo -e "${YELLOW}*** DEBUG BUILD ***${NC}"
    fi
    echo "========================================"
    echo ""

    cd "$MODULE_DIR"

    # Determine image name and tag (all use mur- prefix)
    local IMAGE_TAG="latest"
    case "$MODULE" in
        iquam)
            IMAGE_NAME="mur-iquam"
            ;;
        l2p)
            IMAGE_NAME="mur-l2p"
            ;;
        landice)
            IMAGE_NAME="mur-landice"
            ;;
        mrva)
            IMAGE_NAME="mur-mrva"
            ;;
    esac

    # Note: Always use :latest tag so pipeline doesn't need to know about debug mode
    # The debug/production distinction is in the compiled binaries, not the tag

    echo "Building: ${IMAGE_NAME}:${IMAGE_TAG}"
    echo "Context:  ${BUILD_DIR}"
    if [ "$DEBUG_MODE" -eq 1 ]; then
        echo -e "${YELLOW}Debug:    Enabled (symbols, bounds checking, tracebacks)${NC}"
    fi
    echo ""

    # Build with optional build args and no-cache
    local BUILD_ARGS=""
    if [ "$DEBUG_MODE" -eq 1 ]; then
        BUILD_ARGS="--build-arg DEBUG=1"
    fi
    if [ "$NO_CACHE" -eq 1 ]; then
        BUILD_ARGS="$BUILD_ARGS --no-cache"
    fi

    docker build \
        --platform linux/amd64 \
        ${BUILD_ARGS} \
        -t "${IMAGE_NAME}:${IMAGE_TAG}" \
        -f Dockerfile \
        ..

    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✓${NC} Successfully built ${IMAGE_NAME}:${IMAGE_TAG}"
        return 0
    else
        echo ""
        echo -e "${RED}✗${NC} Failed to build ${IMAGE_NAME}:${IMAGE_TAG}"
        return 1
    fi
}

# Parse arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 <module|all> [--debug] [--no-cache]"
    echo ""
    echo "Available modules:"
    echo "  iquam   - In-situ SST processing (IQUAM buoy data)"
    echo "  l2p     - L2P satellite SST processing"
    echo "  landice - Land/ice mask processing"
    echo "  mrva    - Multi-Resolution Variational Analysis"
    echo "  all     - Build all modules"
    echo ""
    echo "Options:"
    echo "  --debug       - Enable debug build with symbols and bounds checking"
    echo "                  (still tags as :latest for seamless pipeline use)"
    echo "  --no-cache    - Force rebuild without using Docker cache"
    echo ""
    echo "Examples:"
    echo "  $0 mrva                      # Build MRVA (production)"
    echo "  $0 mrva --debug              # Build MRVA with debug symbols"
    echo "  $0 mrva --debug --no-cache   # Force full debug rebuild"
    echo "  $0 all                       # Build all modules (production)"
    echo "  $0 all --debug               # Build all modules with debug"
    exit 1
fi

MODULE=$1
shift

# Parse optional flags
while [ $# -gt 0 ]; do
    case "$1" in
        --debug)
            DEBUG_MODE=1
            ;;
        --no-cache)
            NO_CACHE=1
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
    shift
done

# Step 1: Check if base image exists (only once)
echo "========================================"
echo "MUR Module Builder"
if [ "$DEBUG_MODE" -eq 1 ]; then
    echo -e "${YELLOW}*** DEBUG MODE ENABLED ***${NC}"
fi
echo "========================================"
echo ""
echo -e "${BLUE}[1/3]${NC} Checking MATLAB base image..."
if ! docker image inspect "${BASE_IMAGE_FULL}" >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠${NC}  Base image ${BASE_IMAGE_FULL} not found"
    echo "      Building base image first..."
    echo ""
    "${BUILD_DIR}/build_matlab_base.sh"
    echo ""
else
    echo -e "${GREEN}✓${NC}     Base image ${BASE_IMAGE_FULL} exists"
fi

# Step 2: Check network.lic
echo ""
echo -e "${BLUE}[2/3]${NC} Checking license file..."
if [ ! -f "${BUILD_DIR}/network.lic" ]; then
    echo -e "${RED}✗${NC}     network.lic not found"
    echo ""
    echo "Please create network.lic from template:"
    echo "  cd ${BUILD_DIR}"
    echo "  cp network.lic.example network.lic"
    echo "  # Edit network.lic with your license server details"
    exit 1
fi
echo -e "${GREEN}✓${NC}     License file exists"

# Step 3: Build module(s)
echo ""
echo -e "${BLUE}[3/3]${NC} Building modules..."

if [ "$MODULE" == "all" ]; then
    # Build all modules
    FAILED_MODULES=()
    BUILT_MODULES=()

    for mod in "${MODULES[@]}"; do
        if build_module "$mod"; then
            BUILT_MODULES+=("$mod")
        else
            FAILED_MODULES+=("$mod")
        fi
    done

    # Summary
    echo ""
    echo "========================================"
    echo "Build Summary"
    echo "========================================"
    if [ ${#BUILT_MODULES[@]} -gt 0 ]; then
        echo -e "${GREEN}✓${NC} Successfully built:"
        for mod in "${BUILT_MODULES[@]}"; do
            echo "    - $mod"
        done
    fi
    if [ ${#FAILED_MODULES[@]} -gt 0 ]; then
        echo ""
        echo -e "${RED}✗${NC} Failed to build:"
        for mod in "${FAILED_MODULES[@]}"; do
            echo "    - $mod"
        done
        exit 1
    fi

else
    # Validate single module
    case "$MODULE" in
        iquam|l2p|landice|mrva)
            ;;
        *)
            echo -e "${RED}✗${NC} Invalid module: $MODULE"
            echo "Valid modules: iquam, l2p, landice, mrva, all"
            exit 1
            ;;
    esac

    # Build single module
    if ! build_module "$MODULE"; then
        exit 1
    fi

    # Show usage hint
    echo ""
    echo "Run with:"
    case "$MODULE" in
        iquam)
            echo "  docker run --rm mur-iquam:latest <year> <doy>"
            ;;
        l2p)
            echo "  docker run --rm mur-l2p:latest <sensor> <region> <year> <day> <rewrite>"
            ;;
        landice)
            echo "  docker run --rm mur-landice:latest <yyyy-mm-dd>"
            ;;
        mrva)
            echo "  docker run --rm mur-mrva:latest <year> <doy> <mode> [sensors]"
            ;;
    esac

    if [ "$DEBUG_MODE" -eq 1 ]; then
        echo ""
        echo -e "${YELLOW}Debug build notes:${NC}"
        echo "  - Stack traces will show source file and line numbers on crash"
        echo "  - Array bounds violations will be caught at runtime"
        echo "  - Uninitialized variable access will be detected"
        echo "  - Floating-point exceptions (NaN, Inf, div-by-zero) will trap"
    fi

fi

echo ""
echo -e "${GREEN}✓${NC} Build complete!"
