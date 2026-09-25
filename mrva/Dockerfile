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
# infoMatrix storage precision for the main mrva solver. 0 (default) keeps
# real*8. 1 builds it real*4, halving the dominant array -- see the comment
# block at the top of mrva/src/fortran/spmm.f, including the validation it has
# not had. Applied only to the main Fortran build: cx/ carries its own copy of
# spmm.f with no preprocessor guards and cx/Makefile has no -fpp, so the flag
# would be silently ignored there.
ARG INFOMATRIX_R4=0

# ========================================================================
# Stage 1: Fortran Build Stage (Intel oneAPI HPC Toolkit with ifort)
# ========================================================================
FROM intel/oneapi-hpckit:2024.0.1-devel-ubuntu22.04 AS fortran-builder

# Re-declare ARGs after FROM to make them available in this stage
ARG DEBUG
ARG INFOMATRIX_R4

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
    make DEBUG=${DEBUG:-0} INFOMATRIX_R4=${INFOMATRIX_R4:-0} && \
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
    timeout 600s matlab -batch "results = compiler.build.standaloneApplication('mrva4com_container.m', 'TreatInputsAsNumeric', 'off', 'OutputDir', '/tmp/mrva_build', 'ExecutableName', 'MrvaProcessor', 'EmbedArchive', false); compiler.internal.runtime.utils.setInstallerLocation('/app/matlab/MATLAB_Runtime_glnxa64.zip'); compiler.runtime.customInstaller('mrva_runtime', results, OutputDir='/tmp/runtime_installer', RuntimeDelivery='installer'); disp('Custom installer generated successfully');" || \
    (echo "ERROR: MATLAB build step failed for mrva." && echo "  This covers BOTH license checkout AND runtime-installer packaging." && echo "  'Invalid MATLAB Runtime installer' => the installer in the base image does" && echo "  not match the installed MATLAB; rebuild mur-matlab-base (its digest pin)." && echo "  A license-server timeout => check connectivity to the servers in network.lic." && exit 1) && \
    echo "Verifying compiled files:" && \
    ls -lh /tmp/mrva_build/

# ========================================================================
# Stage 3: Minimal Debian runtime stage with custom MATLAB Runtime
# ========================================================================
FROM debian:bookworm-slim

# Re-declare build args to persist in runtime image
ARG DEBUG=0

# Persist build flags as environment variables for runtime detection
# If built with DEBUG=1, runtime will automatically enable debug output
ENV MRVA_DEBUG_BUILD=${DEBUG}

# Install runtime dependencies
# libxt6, libxmu6: Required by MATLAB Runtime for X11 components even in headless mode
# awscli: used by common/bin/localize.sh (sourced by entrypoint.sh below) to
# fetch s3:// input hrefs (direct-value flags and --sensor-inputs-manifest
# entries) to local disk before MATLAB runs -- see
# docs/input-contract.html section 4.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libc6 \
    libstdc++6 \
    zlib1g \
    unzip \
    libgomp1 \
    libxt6 \
    libxmu6 \
    awscli \
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
# HOME must point at a writable path so the MATLAB Runtime CTF extractor works
# when the container is run with an arbitrary --user <uid> that isn't present in
# /etc/passwd (getpwuid() returns NULL → default HOME of `/` is not writable).
ENV HOME=/tmp

# Stack size configuration for Fortran executables
# The PCG solver uses large local arrays that can overflow the default stack
# Setting unlimited stack and large OpenMP stack prevents segfaults
# These can be overridden at runtime with -e flags
# Use KMP_STACKSIZE (Intel OpenMP runtime uses this; OMP_STACKSIZE would be ignored)
ENV KMP_STACKSIZE=128M

# Create data directories. Inputs are no longer bind-mounted whole
# directories (see entrypoint.sh) -- only output/working paths are
# pre-created here. Scratch dirs under /tmp (/tmp/mrva_tmp, /tmp/.matlab,
# MCR cache) are NOT pre-created: the sticky bit on /tmp would otherwise
# block the runtime UID from rmdir'ing a root-owned dir. Letting the app
# create them at runtime means they're owned by the runtime UID.
RUN mkdir -p /data/output/csp \
             /data/output/netcdf \
             /data/cache \
             /data/logs

# Set working directory
WORKDIR /data

# Shared input-localization helper (source: common/bin/localize.sh), sourced
# by entrypoint.sh below. Copied into the runtime stage directly -- unlike
# common/*.m above, this is bash, not MATLAB source to be compiled away, so
# it has to persist into this final image.
COPY common/bin/localize.sh /opt/common/bin/localize.sh
# Mints DAAC credentials from a MAAP token, so the container can read
# a bucket its own role cannot. stdlib only -- no new dependencies.
COPY common/bin/maap_credentials.py /opt/common/bin/maap_credentials.py
RUN chmod +x /opt/common/bin/localize.sh

# Entrypoint wrapper script (source: mrva/bin/entrypoint.sh).
# Named-args only (--year --doy --mode plus the explicit static/dynamic
# input flags and --sensor-inputs-manifest); every FILE/DIR flag accepts
# either a local path or an s3:// href, resolved via localize.sh.
COPY mrva/bin/entrypoint.sh /opt/mrva/bin/entrypoint.sh
RUN chmod +x /opt/mrva/bin/entrypoint.sh

# Rootless / arbitrary-UID support (OpenShift pattern):
# Assign group 0 (root group) and grant group perms equal to owner perms on all
# paths the app may write to. Any UID added to group 0 at runtime (via
# `docker run --group-add 0`) can then read/write these paths.
# setgid on directories so new files/dirs inherit group 0.
RUN chgrp -R 0 /data /opt/mrva && \
    chmod -R g=u /data /opt/mrva && \
    find /data /opt/mrva -type d -exec chmod g+s {} +

# Set entrypoint
ENTRYPOINT ["/opt/mrva/bin/entrypoint.sh"]

# Default command shows help/usage by providing no arguments (will error with usage info)
CMD []

# Labels for metadata
# org.opencontainers.image.source connects the pushed package to the
# repository on GHCR. Images are pushed by hand (no CI can reach the JPL
# licence servers), so without this label a package lands unlinked and has
# to be connected through the web UI.
LABEL org.opencontainers.image.source="https://github.com/podaac/mur"
LABEL description="MUR MRVA (Multi-Resolution Variational Analysis) Module - Container Wrapper"
LABEL version="1.4"
LABEL maintainer="MUR Team"
LABEL build-pattern="3-stage: (1) Intel ifort Fortran build, (2) MATLAB compilation, (3) Base runtime image"
LABEL base-image="mur-matlab-base:r2024b"
LABEL compiler="Intel Fortran Compiler (ifort) from oneAPI HPC Toolkit 2024.0.1"
LABEL compiler-flags-production="-80 -qopenmp -pad -ipo -O3 -no-prec-div -fp-model fast=2 -xHost"
LABEL compiler-flags-debug="-80 -qopenmp -g -traceback -check bounds -check uninit -fpe0 -warn all -O0"
LABEL build-arg-debug="Set DEBUG=1 for debug build with symbols and bounds checking"
LABEL interface="Named args only: --year --doy --mode plus explicit static/dynamic input flags and --sensor-inputs-manifest"
LABEL fortran-executables="mrva, samplegdscsp, spgrid, trimbip3, makehiresgrid, cbscxdata, cbscxcoeff, cbscxcoeffvector"

# Usage notes:
# Build from mrva directory with parent context to access both mrva/ and common/:
#   cd /path/to/mur/mrva
#   docker build --platform linux/amd64 -t mrva:latest -f Dockerfile ..
#
# Run — every input is an explicit named flag; --sensor-inputs-manifest lists
# exactly which BIC/iQuam files this run needs (a JSON manifest, path or
# s3:// href, entries tagged with `sensor` and `relative_path` -- see
# docs/input-contract.html section 3), localized to local disk by common/bin/localize.sh before
# MATLAB runs:
#   docker run --rm \
#     --memory=64g \
#     --shm-size=4g \
#     -v /path/to/manifest.json:/data/manifest.json:ro \
#     -v /path/to/sensor_data:/path/to/sensor_data:ro \
#     -v /path/to/static-resources:/path/to/static-resources:ro \
#     -v /path/to/landice-output:/path/to/landice-output:ro \
#     -v /path/to/output:/data/output \
#     -v /path/to/cache:/data/cache \
#     mrva:latest \
#     --year 2025 --doy 220 --mode nrt \
#     --polar-cap-edge-file /path/to/static-resources/landice/CylinderP01_edge.bip \
#     --seasonal-file /path/to/static-resources/seasonal/mur_220.nc \
#     --landice-ice-p011-file /path/to/landice-output/Global_ice_2025_220.bip \
#     --landice-grid-p01-file /path/to/landice-output/landiceP01_2025_220.gds.gz \
#     --landice-icefiles-p011-file /path/to/landice-output/icefiles_2025_220.txt \
#     --sensor-inputs-manifest /data/manifest.json \
#     --l4-reference-root /path/to/static-resources/L4
#
# Optional flags: --sensors (comma-separated, default: all configured),
# --mur25-grid-file (absent -> skip MUR25 generation), --prior-csp-file
# (absent -> bootstrap reference field from L4 instead), --debug.
#
# Output directories stay fixed container-internal bind mounts
# (/data/output, /data/cache), unchanged from before -- only the input side
# became explicit. run_mur_pipeline.py / run_mur_maap.py build the manifest
# and resolve every flag value automatically; you don't need to hand-write
# these for normal pipeline runs.
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
