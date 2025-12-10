# Multi-stage Dockerfile for building and deploying MRVA (Multi-Resolution Variational Analysis)
#
# IMPORTANT: This build requires access to MATLAB license servers during compilation.
# If the license server is unreachable, the build may fail with a timeout error.
# Ensure network connectivity to the license servers before building.
#
# Build from the mrva directory with parent context to access both mrva/ and common/:
#   cd mur/mrva
#   docker build --platform linux/amd64 -t mrva:latest -f Dockerfile ..
#
# Debug build (enables debug symbols, bounds checking, stack traces):
#   docker build --platform linux/amd64 --build-arg DEBUG=1 -t mrva:debug -f Dockerfile ..
#
# The .dockerignore file in this directory controls what gets included from parent context
#
# ========================================================================
# Build Arguments
# ========================================================================
# DEBUG: Set to 1 to enable debug build with symbols, bounds checking, and tracebacks
#        Default is 0 (production build with full optimizations)
ARG DEBUG=0

# ========================================================================
# Stage 1: Fortran Build Stage (Intel oneAPI HPC Toolkit with ifort)
# ========================================================================
FROM intel/oneapi-hpckit:2024.0.1-devel-ubuntu22.04 AS fortran-builder

# Re-declare ARG after FROM to make it available in this stage
ARG DEBUG

# Remove problematic Intel GPU repository (not needed for Fortran compilation)
RUN rm -f /etc/apt/sources.list.d/intel-graphics.list 2>/dev/null || true

# Install basic build dependencies
RUN apt-get update && apt-get install -y \
    make \
    && rm -rf /var/lib/apt/lists/*

# Set up Intel oneAPI environment
ENV ONEAPI_ROOT=/opt/intel/oneapi
ENV INTEL_FORTRAN_HOME=${ONEAPI_ROOT}/compiler/latest

# Create Fortran build directory
WORKDIR /app/fortran

# Copy Fortran source files and Makefile
COPY mrva/src/fortran/*.f /app/fortran/
COPY mrva/src/fortran/Makefile /app/fortran/

# Copy cubic B-spline (cx) source files
COPY mrva/src/fortran/cx/*.f /app/fortran/cx/
COPY mrva/src/fortran/cx/Makefile /app/fortran/cx/

# Update Makefiles to use ifort from oneAPI (just update the path, keep optimization flags)
# The original Makefiles use Intel-specific flags: -80 -qopenmp -pad -ipo -O3 -no-prec-div -fp-model fast=2 -xHost
RUN sed -i 's|^FC = /opt/intel/bin/ifort|FC = ifort|g' /app/fortran/Makefile && \
    sed -i 's|^FC = /opt/intel/bin/ifort|FC = ifort|g' /app/fortran/cx/Makefile && \
    sed -i 's|^default:.*|default: cbscxdata cbscxcoeff cbscxcoeffvector|g' /app/fortran/cx/Makefile && \
    echo "Using Intel Fortran compiler (ifort) from oneAPI:" && \
    grep -E "^FC|^FCOPT" /app/fortran/Makefile && \
    grep -E "^FC|^FCOPT" /app/fortran/cx/Makefile

# Build Fortran executables with Intel ifort compiler
# Main executables: mrva, samplegdscsp, spgrid, trimbip3, makehiresgrid
# Spline executables: cbscxdata, cbscxcoeff, cbscxcoeffvector
#
# Build modes (controlled by DEBUG build arg):
#   DEBUG=0 (default): Production build with full optimizations
#     -80 -qopenmp -pad -ipo -O3 -no-prec-div -fp-model fast=2 -xHost -fpp
#   DEBUG=1: Debug build with symbols, bounds checking, and tracebacks
#     -80 -qopenmp -fpp -g -traceback -check bounds -check uninit -fpe0 -warn all -O0
#
# Note: Intel oneAPI environment is already configured in the base image
# -fpp: Enable Fortran preprocessor for #ifdef directives
SHELL ["/bin/bash", "-c"]
RUN cd /app/fortran && \
    echo "Starting Fortran compilation with Intel ifort..." && \
    echo "DEBUG mode: ${DEBUG:-0}" && \
    if [ "${DEBUG}" = "1" ]; then \
        echo "*** DEBUG BUILD: Enabling debug symbols, bounds checking, and tracebacks ***"; \
    else \
        echo "*** PRODUCTION BUILD: Full optimizations enabled ***"; \
    fi && \
    ifort --version && \
    make clean && \
    make DEBUG=${DEBUG:-0} && \
    echo "Main Fortran executables compiled successfully" && \
    echo "Verifying main executables:" && \
    ls -lh /app/fortran/mrva \
           /app/fortran/samplegdscsp \
           /app/fortran/spgrid \
           /app/fortran/trimbip3 \
           /app/fortran/makehiresgrid && \
    echo "" && \
    echo "Building cubic B-spline utilities..." && \
    cd /app/fortran/cx && \
    make clean && \
    make DEBUG=${DEBUG:-0} && \
    echo "Spline utilities compiled successfully" && \
    echo "Verifying spline executables:" && \
    ls -lh /app/fortran/cx/cbscxdata \
           /app/fortran/cx/cbscxcoeff \
           /app/fortran/cx/cbscxcoeffvector

# ========================================================================
# Stage 2: MATLAB Build Stage using shared base
# ========================================================================
FROM mur-matlab-base:r2024b AS matlab-builder

# Switch to matlab user
USER matlab
WORKDIR /app/matlab

# Copy all MATLAB source files into single directory (like old code)
# This makes it easier for MATLAB to find dependencies without complex path setup
COPY --chown=matlab:matlab mrva/src/matlab/workflow/*.m /app/matlab/
COPY --chown=matlab:matlab mrva/src/matlab/preprocessing/*.m /app/matlab/
COPY --chown=matlab:matlab mrva/src/matlab/io/*.m /app/matlab/
COPY --chown=matlab:matlab mrva/src/matlab/output/*.m /app/matlab/
COPY --chown=matlab:matlab mrva/src/matlab/metadata/*.m /app/matlab/
COPY --chown=matlab:matlab mrva/src/matlab/ice/*.m /app/matlab/
COPY --chown=matlab:matlab common/julian.m /app/matlab/
COPY --chown=matlab:matlab common/fortwrite.m /app/matlab/
COPY --chown=matlab:matlab common/fortread.m /app/matlab/

# Copy the containerized entry point
COPY --chown=matlab:matlab mrva/src/matlab/workflow/mrva4com_container.m /app/matlab/

# Compile application & build custom installer
RUN cd /app/matlab && \
    mkdir -p /tmp/mrva_build && \
    echo "Starting MATLAB compilation..." && \
    echo "  Main entry: mrva4com_container.m" && \
    echo "  All dependencies in: /app/matlab/" && \
    timeout 600s matlab -batch "results = compiler.build.standaloneApplication('mrva4com_container.m', 'TreatInputsAsNumeric', 'off', 'OutputDir', '/tmp/mrva_build', 'ExecutableName', 'MrvaProcessor', 'EmbedArchive', false); compiler.internal.runtime.utils.setInstallerLocation('/app/matlab/MATLAB_Runtime_R2024b_Update_6_glnxa64.zip'); compiler.runtime.customInstaller('mrva_runtime', results, OutputDir='/tmp/runtime_installer', RuntimeDelivery='installer'); disp('Custom installer generated successfully');" || \
    (echo "ERROR: Compilation failed. Check license availability." && exit 1) && \
    echo "Verifying compiled files:" && \
    ls -lh /tmp/mrva_build/

# ========================================================================
# Stage 3: Minimal Debian runtime stage with custom MATLAB Runtime
# ========================================================================
FROM debian:bookworm-slim

# Install runtime dependencies
# libxt6, libxmu6: Required by MATLAB Runtime for X11 components even in headless mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libc6 \
    libstdc++6 \
    zlib1g \
    unzip \
    libgomp1 \
    libxt6 \
    libxmu6 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/cache/apt/*

# Copy custom MATLAB Runtime installer from builder stage
COPY --from=matlab-builder /tmp/runtime_installer/ /tmp/runtime_installer/

# Install custom MATLAB Runtime
RUN cd /tmp/runtime_installer && \
    chmod +x mrva_runtime.install && \
    ./mrva_runtime.install -mode silent -agreeToLicense yes -destinationFolder /opt/matlabruntime && \
    rm -rf /tmp/runtime_installer

# Copy Intel OpenMP and runtime libraries needed by ifort-compiled executables
# These are required for executables compiled with -qopenmp flag
COPY --from=fortran-builder /opt/intel/oneapi/compiler/latest/lib/libiomp5.so /usr/lib/x86_64-linux-gnu/
COPY --from=fortran-builder /opt/intel/oneapi/compiler/latest/lib/libifport.so.5 /usr/lib/x86_64-linux-gnu/
COPY --from=fortran-builder /opt/intel/oneapi/compiler/latest/lib/libifcoremt.so.5 /usr/lib/x86_64-linux-gnu/
COPY --from=fortran-builder /opt/intel/oneapi/compiler/latest/lib/libimf.so /usr/lib/x86_64-linux-gnu/
COPY --from=fortran-builder /opt/intel/oneapi/compiler/latest/lib/libsvml.so /usr/lib/x86_64-linux-gnu/
COPY --from=fortran-builder /opt/intel/oneapi/compiler/latest/lib/libirng.so /usr/lib/x86_64-linux-gnu/
COPY --from=fortran-builder /opt/intel/oneapi/compiler/latest/lib/libintlc.so.5 /usr/lib/x86_64-linux-gnu/

# Update library cache
RUN ldconfig

# Create application directory
RUN mkdir -p /opt/mrva/bin

# Copy Fortran executables from fortran-builder stage
COPY --from=fortran-builder /app/fortran/mrva /opt/mrva/bin/
COPY --from=fortran-builder /app/fortran/samplegdscsp /opt/mrva/bin/
COPY --from=fortran-builder /app/fortran/spgrid /opt/mrva/bin/
COPY --from=fortran-builder /app/fortran/trimbip3 /opt/mrva/bin/
COPY --from=fortran-builder /app/fortran/makehiresgrid /opt/mrva/bin/

# Copy cubic B-spline executables from fortran-builder stage
COPY --from=fortran-builder /app/fortran/cx/cbscxdata /opt/mrva/bin/
COPY --from=fortran-builder /app/fortran/cx/cbscxcoeff /opt/mrva/bin/
COPY --from=fortran-builder /app/fortran/cx/cbscxcoeffvector /opt/mrva/bin/

# Copy compiled MATLAB application and separate CTF file from matlab-builder stage
COPY --from=matlab-builder /tmp/mrva_build/MrvaProcessor /opt/mrva/bin/
COPY --from=matlab-builder /tmp/mrva_build/run_MrvaProcessor.sh /opt/mrva/bin/
COPY --from=matlab-builder /tmp/mrva_build/MrvaProcessor.ctf /opt/mrva/bin/

# Make all executables executable
RUN chmod +x /opt/mrva/bin/*

# Set environment variables for MATLAB Runtime
# Note: Official MathWorks runtime container handles MCR paths automatically
# With -C flag, CTF extracts to directory next to executable, not MCR cache
ENV MCR_CACHE_ROOT=/tmp
ENV AGREE_TO_MATLAB_RUNTIME_LICENSE=yes
ENV MCR_INHIBIT_CTF_LOCK=1
ENV MATLAB_LOG_DIR=/data/logs
ENV MATLAB_PREFDIR=/tmp/.matlab
ENV TMP_DIR=/tmp/mrva_tmp
ENV PATH="/opt/mrva/bin:${PATH}"

# Stack size configuration for Fortran executables
# The PCG solver uses large local arrays that can overflow the default stack
# Setting unlimited stack and large OpenMP stack prevents segfaults
# These can be overridden at runtime with -e flags
ENV OMP_STACKSIZE=128M
ENV KMP_STACKSIZE=128M

# Create data directories with proper structure
RUN mkdir -p /data/input/bic \
             /data/input/iquam \
             /data/input/landice \
             /data/output/csp \
             /data/output/netcdf \
             /data/cache \
             /data/logs \
             /tmp/mrva_tmp

# Set working directory
WORKDIR /data

# Create entrypoint wrapper script
# This wrapper validates arguments and calls MATLAB with Fortran binaries available
# Arguments: year doy mode [sensors]
RUN cat > /opt/mrva/bin/entrypoint.sh <<'EOF' && chmod +x /opt/mrva/bin/entrypoint.sh
#!/bin/bash
# MRVA Container Entrypoint Wrapper
set -e

# ========================================================================
# Stack Size Configuration
# ========================================================================
# The Fortran PCG solver uses large local arrays that can exceed default stack
# Setting unlimited stack prevents segmentation faults during solver iterations
# OMP_STACKSIZE/KMP_STACKSIZE set thread stack for OpenMP parallel regions
ulimit -s unlimited 2>/dev/null || echo "Warning: Could not set unlimited stack size"

# Ensure OpenMP stack is set (may have been set in Dockerfile ENV but ensure here)
export OMP_STACKSIZE=${OMP_STACKSIZE:-128M}
export KMP_STACKSIZE=${KMP_STACKSIZE:-128M}

# Argument validation
if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
    echo "ERROR: Expected 3-4 arguments, got $#"
    echo "Usage: docker run ... YEAR DOY MODE [SENSORS]"
    echo "  YEAR:    4-digit year (e.g., 2025)"
    echo "  DOY:     Day of year (1-366)"
    echo "  MODE:    nrt (near-real-time) or rea (reanalysis)"
    echo "  SENSORS: Optional comma-separated list (e.g., AMSR2R,MODISA)"
    echo ""
    echo "Example:"
    echo "  docker run --rm \\"
    echo "    -v /local/l2p:/data/input/bic \\"
    echo "    -v /local/iquam:/data/input/iquam \\"
    echo "    -v /local/landice:/data/input/landice \\"
    echo "    -v /local/output:/data/output \\"
    echo "    mrva:latest 2025 220 nrt"
    exit 1
fi

YEAR=$1
DOY=$2
MODE=$3
SENSORS=${4:-""}

# Validate year
if [ "$YEAR" -lt 1900 ] || [ "$YEAR" -gt 2100 ]; then
    echo "ERROR: Invalid year: $YEAR"
    exit 1
fi

# Validate DOY
if [ "$DOY" -lt 1 ] || [ "$DOY" -gt 366 ]; then
    echo "ERROR: Invalid day of year: $DOY"
    exit 1
fi

# Validate mode
if [ "$MODE" != "nrt" ] && [ "$MODE" != "rea" ]; then
    echo "ERROR: Invalid mode: $MODE (must be 'nrt' or 'rea')"
    exit 1
fi

# Log startup
echo "========================================="
echo "MRVA Container Starting"
echo "========================================="
echo "Year:     $YEAR"
echo "DOY:      $DOY"
echo "Mode:     $MODE"
echo "Sensors:  ${SENSORS:-all (default)}"
echo "-----------------------------------------"
echo "Stack:    $(ulimit -s) (soft limit)"
echo "OMP_STACKSIZE: $OMP_STACKSIZE"
echo "KMP_STACKSIZE: $KMP_STACKSIZE"
echo "========================================="
echo ""

# Ensure Fortran binaries are in PATH
export PATH="/opt/mrva/bin:$PATH"

# Verify Fortran executables are available
echo "Verifying Fortran executables..."
for exe in mrva samplegdscsp spgrid trimbip3 makehiresgrid cbscxdata cbscxcoeff cbscxcoeffvector; do
    if [ ! -x "/opt/mrva/bin/$exe" ]; then
        echo "ERROR: Fortran executable not found: $exe"
        exit 1
    fi
done
echo "  ✓ All Fortran executables found (including spline utilities)"
echo ""

# Call MATLAB executable with arguments
echo "Starting MATLAB runtime..."
if [ -z "$SENSORS" ]; then
    exec /opt/mrva/bin/run_MrvaProcessor.sh "/opt/matlabruntime/R2024b" "$YEAR" "$DOY" "$MODE"
else
    exec /opt/mrva/bin/run_MrvaProcessor.sh "/opt/matlabruntime/R2024b" "$YEAR" "$DOY" "$MODE" "$SENSORS"
fi
EOF

# Set entrypoint
ENTRYPOINT ["/opt/mrva/bin/entrypoint.sh"]

# Default command shows help/usage by providing no arguments (will error with usage info)
CMD []

# Labels for metadata
LABEL description="MUR MRVA (Multi-Resolution Variational Analysis) Module - Container Wrapper"
LABEL version="1.4"
LABEL maintainer="MUR Team"
LABEL build-pattern="3-stage: (1) Intel ifort Fortran build, (2) MATLAB compilation, (3) Base runtime image"
LABEL base-image="mur-matlab-base:r2024b"
LABEL compiler="Intel Fortran Compiler (ifort) from oneAPI HPC Toolkit 2024.0.1"
LABEL compiler-flags-production="-80 -qopenmp -pad -ipo -O3 -no-prec-div -fp-model fast=2 -xHost"
LABEL compiler-flags-debug="-80 -qopenmp -g -traceback -check bounds -check uninit -fpe0 -warn all -O0"
LABEL build-arg-debug="Set DEBUG=1 for debug build with symbols and bounds checking"
LABEL interface="4-arg interface: year doy mode [sensors]"
LABEL fortran-executables="mrva, samplegdscsp, spgrid, trimbip3, makehiresgrid, cbscxdata, cbscxcoeff, cbscxcoeffvector"

# Usage notes:
# Build from mrva directory with parent context to access both mrva/ and common/:
#   cd /path/to/mur/mrva
#   docker build --platform linux/amd64 -t mrva:latest -f Dockerfile ..
#
# Run with container interface (3-4 arguments):
#   docker run --rm \
#     --memory=64g \
#     --shm-size=4g \
#     -v /path/to/l2p:/data/input/bic \
#     -v /path/to/iquam:/data/input/iquam \
#     -v /path/to/landice:/data/input/landice \
#     -v /path/to/output:/data/output \
#     -v /path/to/cache:/data/cache \
#     mrva:latest \
#     2025 220 nrt
#
# Arguments:
#   year:    4-digit year (e.g., 2025)
#   doy:     Day of year (1-366)
#   mode:    'nrt' for near-real-time (L0=6) or 'rea' for reanalysis (L0=2)
#   sensors: Optional comma-separated sensor list (default: all configured)
#
# The container automatically uses:
#   /data/input/bic/     - L2P satellite data (BIC.gz files by sensor)
#   /data/input/iquam/   - Buoy data (BII files)
#   /data/input/landice/ - Land/ice masks (GDS files)
#   /data/output/csp/    - Coefficient files output (CSP format)
#   /data/output/netcdf/ - Final NetCDF4 products (GHRSST L4)
#   /data/cache/         - Temporary working files (BIQ, intermediate)
#   /data/logs/          - Execution logs
#
# Example with custom local paths:
#   docker run --rm \
#     --memory=64g \
#     --shm-size=4g \
#     -v /local/preprocessing/l2p:/data/input/bic \
#     -v /local/preprocessing/iquam:/data/input/iquam \
#     -v /local/preprocessing/landice:/data/input/landice \
#     -v /local/mrva/output:/data/output \
#     -v /local/mrva/cache:/data/cache \
#     -v /local/logs:/data/logs \
#     mrva:latest \
#     2025 220 nrt AMSR2R,MODISA
#
# Memory Requirements:
#   - NRT mode (L0=6 to LF=11): ~32GB recommended
#   - REA mode (L0=2 to LF=11): ~64GB recommended
#   - L=11 grid: 51712 × 23040 = 1.19 billion points
#
# Performance Note:
#   --shm-size=4g recommended for optimal MATLAB Runtime performance
#   OpenMP parallelization enabled in Fortran (uses all available cores)
