# Multi-stage Dockerfile for building and deploying L2P application
#
# IMPORTANT: This build requires access to MATLAB license servers during compilation.
# If the license server is unreachable, the build may fail with a timeout error.
# Ensure network connectivity to the license servers before building.
#
# Build from the l2p directory with parent context:
#   cd mur/l2p
#   docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..
#
# The l2p/.dockerignore file controls what gets included from parent directory
#
# Stage 1: MATLAB Build Stage using shared base
FROM mur-matlab-base:r2024b AS builder

# Switch to matlab user
USER matlab
WORKDIR /app/matlab

# Copy the l2p application source code
# Note: Build context is parent directory (mur/), so paths are relative to that
# .dockerignore in parent controls what gets included
COPY --chown=matlab:matlab l2p/src/*.m /app/matlab/

# Copy shared utilities from common folder
COPY --chown=matlab:matlab common/julian.m /app/matlab/
COPY --chown=matlab:matlab common/fortwrite.m /app/matlab/

# Compile application & build custom installer
RUN cd /app/matlab && \
    mkdir -p /tmp/l2p_build && \
    echo "Starting MATLAB compilation..." && \
    echo "  Main entry: l2p_wrapper.m" && \
    echo "  All dependencies in: /app/matlab/" && \
    timeout 600s matlab -batch "results = compiler.build.standaloneApplication('l2p_wrapper.m', 'TreatInputsAsNumeric', 'off', 'OutputDir', '/tmp/l2p_build', 'ExecutableName', 'L2pProcessor', 'EmbedArchive', false); compiler.internal.runtime.utils.setInstallerLocation('/app/matlab/MATLAB_Runtime_R2024b_Update_6_glnxa64.zip'); compiler.runtime.customInstaller('l2p_runtime', results, OutputDir='/tmp/runtime_installer', RuntimeDelivery='installer'); disp('Custom installer generated successfully');" || \
    (echo "ERROR: Compilation failed. Check license availability." && exit 1) && \
    echo "Verifying compiled files:" && \
    ls -lh /tmp/l2p_build/

# ========================================================================
# Stage 2: Minimal Debian runtime stage with custom MATLAB Runtime
# ========================================================================
FROM debian:bookworm-slim

# Install runtime dependencies
# libxt6, libxmu6: Required by MATLAB Runtime for X11 components even in headless mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libc6 \
    libstdc++6 \
    wget \
    zlib1g \
    unzip \
    gzip \
    bzip2 \
    libgomp1 \
    libxt6 \
    libxmu6 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/cache/apt/*

# Copy custom MATLAB Runtime installer from builder stage
COPY --from=builder /tmp/runtime_installer/ /tmp/runtime_installer/

# Install custom MATLAB Runtime
RUN cd /tmp/runtime_installer && \
    chmod +x l2p_runtime.install && \
    ./l2p_runtime.install -mode silent -agreeToLicense yes -destinationFolder /opt/matlabruntime && \
    rm -rf /tmp/runtime_installer

# Create application directory
RUN mkdir -p /opt/l2p/bin

# Copy compiled application and separate CTF file from builder stage
COPY --from=builder /tmp/l2p_build/L2pProcessor /opt/l2p/bin/
COPY --from=builder /tmp/l2p_build/run_L2pProcessor.sh /opt/l2p/bin/
COPY --from=builder /tmp/l2p_build/L2pProcessor.ctf /opt/l2p/bin/

# Make executable
RUN chmod +x /opt/l2p/bin/L2pProcessor /opt/l2p/bin/run_L2pProcessor.sh

# Set environment variables for MATLAB Runtime
ENV MCR_CACHE_ROOT=/tmp
ENV AGREE_TO_MATLAB_RUNTIME_LICENSE=yes
ENV MCR_INHIBIT_CTF_LOCK=1
ENV MATLAB_LOG_DIR=/data/logs
ENV MATLAB_PREFDIR=/tmp/.matlab
ENV TMP_DIR=/tmp/l2p_tmp
# HOME must point at a writable path so the MATLAB Runtime CTF extractor works
# when the container is run with an arbitrary --user <uid> that isn't present in
# /etc/passwd (getpwuid() returns NULL → default HOME of `/` is not writable).
ENV HOME=/tmp

# Create data/scratch directories (MATLAB_PREFDIR is pre-created so permissions can be set below)
RUN mkdir -p /data/input \
             /data/output \
             /data/logs \
             /tmp/l2p_tmp \
             /tmp/.matlab

# Set working directory
WORKDIR /data

# Create entrypoint wrapper script
# This wrapper uses fixed container paths (/data/input, /data/output)
# Arguments: sensor region year day rewrite (5 args instead of 7)
RUN echo '#!/bin/bash' > /opt/l2p/bin/entrypoint.sh && \
    echo '# L2P Container Entrypoint Wrapper' >> /opt/l2p/bin/entrypoint.sh && \
    echo 'set -e' >> /opt/l2p/bin/entrypoint.sh && \
    echo '' >> /opt/l2p/bin/entrypoint.sh && \
    echo 'if [ "$#" -ne 5 ]; then' >> /opt/l2p/bin/entrypoint.sh && \
    echo '    echo "ERROR: Expected 5 arguments, got $#"' >> /opt/l2p/bin/entrypoint.sh && \
    echo '    echo "Usage: docker run ... SENSOR REGION YEAR DAY REWRITE"' >> /opt/l2p/bin/entrypoint.sh && \
    echo '    echo "  SENSOR:  AMSR2R, AVMTBG, MODISA, MODIST"' >> /opt/l2p/bin/entrypoint.sh && \
    echo '    echo "  REGION:  Global"' >> /opt/l2p/bin/entrypoint.sh && \
    echo '    echo "  YEAR:    4-digit year (e.g., 2025)"' >> /opt/l2p/bin/entrypoint.sh && \
    echo '    echo "  DAY:     Day of year (1-366)"' >> /opt/l2p/bin/entrypoint.sh && \
    echo '    echo "  REWRITE: 0=skip existing, 1=overwrite"' >> /opt/l2p/bin/entrypoint.sh && \
    echo '    exit 1' >> /opt/l2p/bin/entrypoint.sh && \
    echo 'fi' >> /opt/l2p/bin/entrypoint.sh && \
    echo '' >> /opt/l2p/bin/entrypoint.sh && \
    echo '# Fixed paths managed by Docker volume mounts' >> /opt/l2p/bin/entrypoint.sh && \
    echo 'INDIR="/data/input"' >> /opt/l2p/bin/entrypoint.sh && \
    echo 'OUTDIR="/data/output"' >> /opt/l2p/bin/entrypoint.sh && \
    echo '' >> /opt/l2p/bin/entrypoint.sh && \
    echo '# Call MATLAB executable with fixed paths inserted' >> /opt/l2p/bin/entrypoint.sh && \
    echo 'exec /opt/l2p/bin/run_L2pProcessor.sh "/opt/matlabruntime/R2024b" "$1" "$2" "$INDIR" "$OUTDIR" "$3" "$4" "$5"' >> /opt/l2p/bin/entrypoint.sh && \
    chmod +x /opt/l2p/bin/entrypoint.sh

# Rootless / arbitrary-UID support (OpenShift pattern):
# Assign group 0 (root group) and grant group perms equal to owner perms on all
# paths the app may write to. Any UID added to group 0 at runtime (via
# `docker run --group-add 0`) can then read/write these paths.
# setgid on directories so new files/dirs inherit group 0.
RUN chgrp -R 0 /data /tmp/.matlab /tmp/l2p_tmp && \
    chmod -R g=u /data /tmp/.matlab /tmp/l2p_tmp && \
    find /data /tmp/.matlab /tmp/l2p_tmp -type d -exec chmod g+s {} +

# Set entrypoint
ENTRYPOINT ["/opt/l2p/bin/entrypoint.sh"]

# Default command shows help/usage by providing no arguments (will error with usage info)
CMD []

# Labels for metadata
LABEL description="MUR L2P Satellite SST Processing Module - Container Wrapper"
LABEL version="3.2"
LABEL maintainer="MUR Team"
LABEL build-pattern="Multi-stage: MATLAB compilation → Base runtime image"
LABEL base-image="mur-matlab-base:r2024b"
LABEL interface="Simplified 5-arg interface: sensor region year day rewrite"
LABEL downloads="Handled separately by cron jobs (not in container)"

# Usage notes:
# Build from l2p directory with parent context:
#   cd /path/to/mur/l2p
#   docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..
#
# Run with simplified container interface (5 arguments):
#   docker run --rm \
#     --shm-size=512M \
#     -v /path/to/input:/data/input \
#     -v /path/to/output:/data/output \
#     mur-l2p:latest \
#     AMSR2R Global 2025 220 0
#
# Arguments (simplified for container - paths managed by volume mounts):
#   sensor:  AMSR2R, AVMTBG, MODISA, or MODIST
#   region:  'Global' (typically always Global)
#   year:    4-digit year (e.g., 2025)
#   day:     Day of year (1-366)
#   rewrite: 0=skip existing files, 1=overwrite existing files
#
# The entrypoint wrapper automatically uses:
#   indir:   /data/input  (mount your L2P files here)
#   bicdir:  /data/output (BIC files written here)
#
# Example with custom local paths:
#   docker run --rm \
#     --shm-size=512M \
#     -v /local/l2p_files:/data/input \
#     -v /local/bic_output:/data/output \
#     mur-l2p:latest \
#     MODISA Global 2025 220 0
#
# IMPORTANT: Downloads are handled separately (like production cron jobs)
#   - Container expects L2P files already present in mounted input directory
#   - Use podaac-data-subscriber or other tools to download files before processing
#   - Production uses hourly cron jobs for downloads
#
# Performance Note: --shm-size=512M recommended for optimal MATLAB Runtime performance
