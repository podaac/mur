# Multi-stage Dockerfile for building and deploying LANDICE application
#
# IMPORTANT: This build requires access to MATLAB license servers during compilation.
# If the license server is unreachable, the build may fail with a timeout error.
# Ensure network connectivity to the license servers before building.
#
# Build from the landice directory with parent context to access both landice/ and common/:
#   cd mur/landice
#   docker build --platform linux/amd64 -t landice:latest -f Dockerfile ..
#
# The .dockerignore file in this directory controls what gets included from parent context
#
# ========================================================================
# Stage 1: MATLAB Build Stage using shared base
# ========================================================================
FROM mur-matlab-base:r2024b AS builder

# Switch to matlab user
USER matlab
WORKDIR /app/matlab

# Copy the landice application source code
COPY --chown=matlab:matlab landice/src/*.m /app/matlab/

# Copy shared utilities from common folder
COPY --chown=matlab:matlab common/*.m /app/matlab/

# Compile application & build custom installer
RUN cd /app/matlab && \
    mkdir -p /tmp/landice_build && \
    echo "Starting MATLAB compilation..." && \
    echo "  Main entry: landice_wrapper.m" && \
    echo "  All dependencies in: /app/matlab/" && \
    timeout 600s matlab -batch "results = compiler.build.standaloneApplication('landice_wrapper.m', 'TreatInputsAsNumeric', 'off', 'OutputDir', '/tmp/landice_build', 'ExecutableName', 'LandiceProcessor', 'EmbedArchive', false); compiler.internal.runtime.utils.setInstallerLocation('/app/matlab/MATLAB_Runtime_R2024b_Update_6_glnxa64.zip'); compiler.runtime.customInstaller('landice_runtime', results, OutputDir='/tmp/runtime_installer', RuntimeDelivery='installer'); disp('Custom installer generated successfully');" || \
    (echo "ERROR: Compilation failed. Check license availability." && exit 1) && \
    echo "Verifying compiled files:" && \
    ls -lh /tmp/landice_build/

# ========================================================================
# Stage 2: Minimal Debian runtime stage with custom MATLAB Runtime
# ========================================================================
FROM debian:bookworm-slim

# Install runtime dependencies including Python3
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
COPY --from=builder /tmp/runtime_installer/ /tmp/runtime_installer/

# Install custom MATLAB Runtime
RUN cd /tmp/runtime_installer && \
    chmod +x landice_runtime.install && \
    ./landice_runtime.install -mode silent -agreeToLicense yes -destinationFolder /opt/matlabruntime && \
    rm -rf /tmp/runtime_installer

# Create application directory
RUN mkdir -p /opt/landice/bin

# Copy compiled application and separate CTF file from builder stage
COPY --from=builder /tmp/landice_build/LandiceProcessor /opt/landice/bin/
COPY --from=builder /tmp/landice_build/run_LandiceProcessor.sh /opt/landice/bin/
COPY --from=builder /tmp/landice_build/LandiceProcessor.ctf /opt/landice/bin/

# Make executables executable
RUN chmod +x /opt/landice/bin/LandiceProcessor /opt/landice/bin/run_LandiceProcessor.sh

# Set environment variables for MATLAB Runtime
ENV MCR_CACHE_ROOT=/tmp
ENV AGREE_TO_MATLAB_RUNTIME_LICENSE=yes
ENV MCR_INHIBIT_CTF_LOCK=1
ENV MATLAB_LOG_DIR=/data/logs
ENV MATLAB_PREFDIR=/tmp/.matlab
ENV TMP_DIR=/tmp/landice_tmp

# Environment variables for OSI SAF FTP paths (to be overridden at runtime)
ENV OSISAF_FTP_REPROCESSED=""
ENV OSISAF_FTP_ARCHIVE=""
ENV OSISAF_FTP_PROD=""

# Create data directories
RUN mkdir -p /data/input /data/output/p011 /data/output/p01 /data/logs /tmp/landice_tmp

# Set working directory
WORKDIR /data

# Create entrypoint wrapper script
# This wrapper uses fixed container paths (/input, /output/p011, /output/p01)
# matching production's separate output directories per resolution.
# Arguments: year doy (2 args, paths are injected by entrypoint)
RUN echo '#!/bin/bash' > /opt/landice/bin/entrypoint.sh && \
    echo '# LANDICE Container Entrypoint Wrapper' >> /opt/landice/bin/entrypoint.sh && \
    echo 'set -e' >> /opt/landice/bin/entrypoint.sh && \
    echo '' >> /opt/landice/bin/entrypoint.sh && \
    echo 'if [ "$#" -ne 2 ]; then' >> /opt/landice/bin/entrypoint.sh && \
    echo '    echo "ERROR: Expected 2 arguments, got $#"' >> /opt/landice/bin/entrypoint.sh && \
    echo '    echo "Usage: docker run ... YEAR DOY"' >> /opt/landice/bin/entrypoint.sh && \
    echo '    echo "  YEAR: 4-digit year (e.g., 2025)"' >> /opt/landice/bin/entrypoint.sh && \
    echo '    echo "  DOY:  Day of year (1-366)"' >> /opt/landice/bin/entrypoint.sh && \
    echo '    exit 1' >> /opt/landice/bin/entrypoint.sh && \
    echo 'fi' >> /opt/landice/bin/entrypoint.sh && \
    echo '' >> /opt/landice/bin/entrypoint.sh && \
    echo '# Fixed paths managed by Docker volume mounts' >> /opt/landice/bin/entrypoint.sh && \
    echo '# Production uses separate paths per resolution:' >> /opt/landice/bin/entrypoint.sh && \
    echo '#   p011 (1km):  /nas/ftp/mur_sst/tmchin/landice/' >> /opt/landice/bin/entrypoint.sh && \
    echo '#   p01 (0.01°): /nas2/landice/' >> /opt/landice/bin/entrypoint.sh && \
    echo 'INDIR="/input"' >> /opt/landice/bin/entrypoint.sh && \
    echo 'OUTDIR_P011="/output/p011"' >> /opt/landice/bin/entrypoint.sh && \
    echo 'OUTDIR_P01="/output/p01"' >> /opt/landice/bin/entrypoint.sh && \
    echo '' >> /opt/landice/bin/entrypoint.sh && \
    echo '# Call MATLAB executable with fixed paths inserted' >> /opt/landice/bin/entrypoint.sh && \
    echo '# landice_wrapper expects: input_dir output_dir_p011 output_dir_p01 year doy' >> /opt/landice/bin/entrypoint.sh && \
    echo 'exec /opt/landice/bin/run_LandiceProcessor.sh "/opt/matlabruntime/R2024b" "$INDIR" "$OUTDIR_P011" "$OUTDIR_P01" "$1" "$2"' >> /opt/landice/bin/entrypoint.sh && \
    chmod +x /opt/landice/bin/entrypoint.sh

# Set entrypoint
ENTRYPOINT ["/opt/landice/bin/entrypoint.sh"]

# Default command shows help/usage by providing no arguments (will error with usage info)
CMD []

# Labels for metadata
LABEL description="MUR LANDICE Processing Module - Container Wrapper"
LABEL version="2.1"
LABEL maintainer="MUR Team"
LABEL build-pattern="Multi-stage: MATLAB compilation → Base runtime image"
LABEL base-image="mur-matlab-base:r2024b"

# Performance Note: When running this container, use --shm-size=512M for optimal MATLAB Runtime performance