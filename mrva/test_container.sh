#!/bin/bash
# Test script for MRVA container
#
# This script validates the MRVA container with sample data
#
# Usage: ./test_container.sh [TEST_TYPE]
#   TEST_TYPE: basic | full (default: basic)
#
# Examples:
#   ./test_container.sh                # Basic validation test
#   ./test_container.sh full           # Full processing test with sample data

set -e

# Parse arguments
TEST_TYPE="${1:-basic}"

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MUR_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================="
echo "MRVA Container Test"
echo "========================================="
echo "Test type: $TEST_TYPE"
echo "========================================="
echo ""

# Function to run basic validation
test_basic() {
    echo "Running basic validation..."
    echo ""

    # Test 1: Check if image exists
    echo "Test 1: Checking if mrva:latest image exists..."
    if docker images mrva:latest | grep -q mrva; then
        echo "  ✓ Image found"
    else
        echo "  ✗ Image not found. Run ./build.sh first"
        exit 1
    fi
    echo ""

    # Test 2: Check entrypoint shows usage
    echo "Test 2: Checking entrypoint shows usage on invalid args..."
    if docker run --rm mrva:latest 2>&1 | grep -q "Usage:"; then
        echo "  ✓ Usage information displayed"
    else
        echo "  ✗ Expected usage information not found"
        exit 1
    fi
    echo ""

    # Test 3: Verify Fortran executables are in container
    echo "Test 3: Checking Fortran executables..."
    EXEC_CHECK=$(docker run --rm --entrypoint /bin/bash mrva:latest -c "ls /opt/mrva/bin/{mrva,spgrid,trimbip3,makehiresgrid,samplegdscsp} 2>&1")
    if echo "$EXEC_CHECK" | grep -q "No such file"; then
        echo "  ✗ Some Fortran executables missing"
        echo "$EXEC_CHECK"
        exit 1
    else
        echo "  ✓ All Fortran executables present"
    fi
    echo ""

    # Test 4: Verify MATLAB executable is in container
    echo "Test 4: Checking MATLAB executable..."
    if docker run --rm --entrypoint /bin/bash mrva:latest -c "test -x /opt/mrva/bin/MrvaProcessor && echo OK" | grep -q "OK"; then
        echo "  ✓ MATLAB executable present"
    else
        echo "  ✗ MATLAB executable not found or not executable"
        exit 1
    fi
    echo ""

    # Test 5: Check directory structure
    # Inputs are no longer pre-created directories (explicit-args contract --
    # every input is now a named flag, localized/materialized at runtime by
    # entrypoint.sh; see documentation/STATIC_DATA.md). Only output/working
    # paths are still pre-created in the image.
    echo "Test 5: Checking directory structure..."
    DIR_CHECK=$(docker run --rm --entrypoint /bin/bash mrva:latest -c "ls -d /data/output /data/cache /data/logs 2>&1")
    if echo "$DIR_CHECK" | grep -q "No such file"; then
        echo "  ✗ Some required directories missing"
        echo "$DIR_CHECK"
        exit 1
    else
        echo "  ✓ All required directories present"
    fi
    echo ""

    echo "========================================="
    echo "Basic validation completed successfully!"
    echo "========================================="
    echo ""
    echo "Container is ready for use."
    echo ""
    echo "To run a full processing test with sample data:"
    echo "  ./test_container.sh full"
    echo ""
}

# Function to run full processing test
test_full() {
    echo "========================================="
    echo "test_full is out of date"
    echo "========================================="
    echo "MRVA now takes every input as an explicit named flag (static-resource"
    echo "files, per-day landice outputs, and a --sensor-inputs-manifest covering"
    echo "BIC/iQuam fan-in) instead of the old bind-mounted /data/input/{bic,iquam,landice}"
    echo "directories + positional YEAR DOY MODE args this script still builds below."
    echo "See mrva/README.md and mrva/bin/entrypoint.sh's usage() for the current"
    echo "interface, or just use run_mur_pipeline.py, which builds all of this"
    echo "automatically (--execute mrva)."
    echo ""
    echo "This function hasn't been rewritten for the new interface yet -- exiting"
    echo "rather than running a command guaranteed to fail against the current"
    echo "entrypoint.sh (which no longer accepts positional args at all)."
    exit 1

    echo "Running full processing test with sample data..."
    echo ""

    # Setup test directories
    TEST_DIR="$MUR_DIR/testing/mrva"
    INPUT_BIC="$TEST_DIR/input/bic"
    INPUT_IQUAM="$TEST_DIR/input/iquam"
    INPUT_LANDICE="$TEST_DIR/input/landice"
    OUTPUT_DIR="$TEST_DIR/output"
    CACHE_DIR="$TEST_DIR/cache"
    LOGS_DIR="$TEST_DIR/logs"

    echo "Creating test directory structure..."
    mkdir -p "$INPUT_BIC" "$INPUT_IQUAM" "$INPUT_LANDICE" "$OUTPUT_DIR" "$CACHE_DIR" "$LOGS_DIR"
    echo "  Test directory: $TEST_DIR"
    echo ""

    # Check if sample data exists
    echo "Checking for sample data..."
    PREPROCESSING_DIR="$MUR_DIR/testing/preprocessing/output"

    if [ -d "$PREPROCESSING_DIR/l2p" ]; then
        echo "  ✓ Found L2P data in preprocessing output"
        # Link or copy sample L2P data
        if [ ! "$(ls -A $INPUT_BIC)" ]; then
            echo "    Linking L2P data to test input..."
            cp -r "$PREPROCESSING_DIR/l2p"/* "$INPUT_BIC/" 2>/dev/null || true
        fi
    else
        echo "  ⚠ No L2P preprocessing data found"
        echo "    Run preprocessing pipeline first to generate test data"
    fi

    if [ -d "$PREPROCESSING_DIR/iquam" ]; then
        echo "  ✓ Found iQUAM data in preprocessing output"
        if [ ! "$(ls -A $INPUT_IQUAM)" ]; then
            echo "    Linking iQUAM data to test input..."
            cp -r "$PREPROCESSING_DIR/iquam"/* "$INPUT_IQUAM/" 2>/dev/null || true
        fi
    else
        echo "  ⚠ No iQUAM preprocessing data found"
    fi

    if [ -d "$PREPROCESSING_DIR/landice" ]; then
        echo "  ✓ Found LandIce data in preprocessing output"
        if [ ! "$(ls -A $INPUT_LANDICE)" ]; then
            echo "    Linking LandIce data to test input..."
            cp -r "$PREPROCESSING_DIR/landice"/* "$INPUT_LANDICE/" 2>/dev/null || true
        fi
    else
        echo "  ⚠ No LandIce preprocessing data found"
    fi
    echo ""

    # Check if we have enough data to proceed
    HAS_BIC=$(find "$INPUT_BIC" -name "*.bic.gz" | wc -l)
    HAS_IQUAM=$(find "$INPUT_IQUAM" -name "*.bii" | wc -l)
    HAS_LANDICE=$(find "$INPUT_LANDICE" -name "*.gds" | wc -l)

    echo "Data availability:"
    echo "  L2P files:     $HAS_BIC"
    echo "  iQUAM files:   $HAS_IQUAM"
    echo "  LandIce files: $HAS_LANDICE"
    echo ""

    if [ "$HAS_BIC" -eq 0 ] || [ "$HAS_IQUAM" -eq 0 ] || [ "$HAS_LANDICE" -eq 0 ]; then
        echo "⚠ WARNING: Insufficient sample data for full processing test"
        echo ""
        echo "To generate sample data, run the preprocessing pipeline:"
        echo "  cd $MUR_DIR"
        echo "  uv run run_mur_pipeline.py --config config.json --date 2024-08-08 --execute landice,iquam,l2p"
        echo ""
        echo "Skipping full processing test."
        exit 0
    fi

    # Run MRVA container with sample data
    echo "Running MRVA container..."
    echo "Command:"
    echo "  docker run --rm \\"
    echo "    --memory=32g --shm-size=4g \\"
    echo "    -v $INPUT_BIC:/data/input/bic \\"
    echo "    -v $INPUT_IQUAM:/data/input/iquam \\"
    echo "    -v $INPUT_LANDICE:/data/input/landice \\"
    echo "    -v $OUTPUT_DIR:/data/output \\"
    echo "    -v $CACHE_DIR:/data/cache \\"
    echo "    -v $LOGS_DIR:/data/logs \\"
    echo "    mrva:latest 2024 221 nrt"
    echo ""

    docker run --rm \
        --memory=32g \
        --shm-size=4g \
        -v "$INPUT_BIC":/data/input/bic \
        -v "$INPUT_IQUAM":/data/input/iquam \
        -v "$INPUT_LANDICE":/data/input/landice \
        -v "$OUTPUT_DIR":/data/output \
        -v "$CACHE_DIR":/data/cache \
        -v "$LOGS_DIR":/data/logs \
        mrva:latest 2024 221 nrt

    echo ""
    echo "========================================="
    echo "Full processing test completed!"
    echo "========================================="
    echo ""
    echo "Output directory: $OUTPUT_DIR"
    echo "Cache directory:  $CACHE_DIR"
    echo "Logs directory:   $LOGS_DIR"
    echo ""
    echo "Check output files:"
    echo "  ls -lh $OUTPUT_DIR"
    echo ""
}

# Run appropriate test
case $TEST_TYPE in
    basic)
        test_basic
        ;;
    full)
        test_full
        ;;
    *)
        echo "Unknown test type: $TEST_TYPE"
        echo "Usage: $0 [basic | full]"
        exit 1
        ;;
esac
