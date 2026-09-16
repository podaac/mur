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
    timeout 600s matlab -batch "results = compiler.build.standaloneApplication('l2p_wrapper.m', 'TreatInputsAsNumeric', 'off', 'OutputDir', '/tmp/l2p_build', 'ExecutableName', 'L2pProcessor', 'EmbedArchive', false); compiler.internal.runtime.utils.setInstallerLocation('/app/matlab/MATLAB_Runtime_glnxa64.zip'); compiler.runtime.customInstaller('l2p_runtime', results, OutputDir='/tmp/runtime_installer', RuntimeDelivery='installer'); disp('Custom installer generated successfully');" || \
    (echo "ERROR: MATLAB build step failed for l2p." && echo "  This covers BOTH license checkout AND runtime-installer packaging." && echo "  'Invalid MATLAB Runtime installer' => the installer in the base image does" && echo "  not match the installed MATLAB; rebuild mur-matlab-base (its digest pin)." && echo "  A license-server timeout => check connectivity to the servers in network.lic." && exit 1) && \
    echo "Verifying compiled files:" && \
    ls -lh /tmp/l2p_build/

# ========================================================================
# Stage 2: Minimal Debian runtime stage with custom MATLAB Runtime
# ========================================================================
FROM debian:bookworm-slim

# Install runtime dependencies
# libxt6, libxmu6: Required by MATLAB Runtime for X11 components even in headless mode
# awscli: used by common/bin/localize.sh (sourced by entrypoint.sh below) to
# fetch s3:// input hrefs (direct-value flags and manifest entries) to local
# disk before MATLAB runs -- see
# docs/input-contract.html section 4.
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
    awscli \
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

# Create data directories. Scratch dirs under /tmp (/tmp/l2p_tmp, /tmp/.matlab,
# MCR cache) are NOT pre-created: the sticky bit on /tmp would otherwise block
# the runtime UID from rmdir'ing a root-owned dir. Letting the app create them
# at runtime means they're owned by the runtime UID.
RUN mkdir -p /data/input \
             /data/output \
             /data/logs

# Set working directory
WORKDIR /data

# Shared input-localization helper (source: common/bin/localize.sh), sourced
# by entrypoint.sh below. Copied into the runtime stage directly -- unlike
# common/julian.m / common/fortwrite.m above, this is bash, not MATLAB source
# to be compiled away, so it has to persist into this final image.
COPY common/bin/localize.sh /opt/common/bin/localize.sh
RUN chmod +x /opt/common/bin/localize.sh

# Entrypoint wrapper script (source: l2p/bin/entrypoint.sh).
# Named-args only (--sensor --region --year --doy --rewrite --granules-manifest);
# --granules-manifest accepts either a local path or an s3:// href, resolved
# via localize.sh.
COPY l2p/bin/entrypoint.sh /opt/l2p/bin/entrypoint.sh
RUN chmod +x /opt/l2p/bin/entrypoint.sh

# Rootless / arbitrary-UID support (OpenShift pattern):
# Assign group 0 (root group) and grant group perms equal to owner perms on all
# paths the app may write to. Any UID added to group 0 at runtime (via
# `docker run --group-add 0`) can then read/write these paths.
# setgid on directories so new files/dirs inherit group 0.
RUN chgrp -R 0 /data /opt/l2p && \
    chmod -R g=u /data /opt/l2p && \
    find /data /opt/l2p -type d -exec chmod g+s {} +

# Set entrypoint
ENTRYPOINT ["/opt/l2p/bin/entrypoint.sh"]

# Default command shows help/usage by providing no arguments (will error with usage info)
CMD []

# Labels for metadata
# org.opencontainers.image.source connects the pushed package to the
# repository on GHCR. Images are pushed by hand (no CI can reach the JPL
# licence servers), so without this label a package lands unlinked and has
# to be connected through the web UI.
LABEL org.opencontainers.image.source="https://github.com/podaac/mur"
LABEL description="MUR L2P Satellite SST Processing Module - Container Wrapper"
LABEL version="3.2"
LABEL maintainer="MUR Team"
LABEL build-pattern="Multi-stage: MATLAB compilation → Base runtime image"
LABEL base-image="mur-matlab-base:r2024b"
LABEL interface="Named args only: --sensor --region --year --doy --rewrite --granules-manifest"
LABEL downloads="Handled separately by cron jobs (not in container)"

# Usage notes:
# Build from l2p directory with parent context:
#   cd /path/to/mur/l2p
#   docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..
#
# Run — every input is an explicit named flag; --granules-manifest lists
# exactly which granule files this run needs (a JSON manifest, path or
# s3:// href -- see docs/input-contract.html section 3), localized to local disk by common/bin/localize.sh before
# MATLAB runs, so the manifest's entries may themselves be local paths
# (bind-mounted) or s3:// hrefs (MAAP):
#   docker run --rm \
#     --shm-size=512M \
#     -v /path/to/manifest.json:/data/manifest.json:ro \
#     -v /path/to/granules:/path/to/granules:ro \
#     -v /path/to/output:/data/output \
#     mur-l2p:latest \
#     --sensor AMSR2R --region Global --year 2025 --doy 220 --rewrite 0 \
#     --granules-manifest /data/manifest.json
#
# Output directory stays a fixed container-internal path (/data/output),
# bind-mounted as before -- outputs are produced, not discovered, so this
# doesn't need to be a flag.
#
# IMPORTANT: Downloads are handled separately (like production cron jobs)
#   - The calling orchestrator (run_mur_pipeline.py / run_mur_maap.py) builds
#     the granules manifest from files it already tracked downloading
#   - Use podaac-data-subscriber or other tools to download files before processing
#   - Production uses hourly cron jobs for downloads
#
# Performance Note: --shm-size=512M recommended for optimal MATLAB Runtime performance
