# Multi-stage Dockerfile for building and deploying IQUAM application
#
# IMPORTANT: This build requires access to MATLAB license servers during compilation.
# If the license server is unreachable, the build may fail with a timeout error.
# Ensure network connectivity to the license servers before building.
#
# Stage 1: MATLAB Build Stage using shared base
FROM mur-matlab-base:r2024b AS builder

# Switch to matlab user
USER matlab
WORKDIR /app/matlab

# Copy the iquam application source code
# Note: Build context is parent directory (mur/), so paths are relative to that
# .dockerignore in parent excludes test data and build artifacts
COPY --chown=matlab:matlab iquam/*.m /app/matlab/

# Copy shared utilities from common folder
COPY --chown=matlab:matlab common/julian.m /app/matlab/
COPY --chown=matlab:matlab common/fortwrite.m /app/matlab/

# Compile application & build custom installer
RUN cd /app/matlab && \
    mkdir -p /tmp/iquam_build && \
    echo "Starting MATLAB compilation..." && \
    echo "  Main entry: buoyDataProcessing.m" && \
    echo "  All dependencies in: /app/matlab/" && \
    timeout 600s matlab -batch "results = compiler.build.standaloneApplication('buoyDataProcessing.m', 'TreatInputsAsNumeric', 'off', 'OutputDir', '/tmp/iquam_build', 'ExecutableName', 'IquamProcessor', 'EmbedArchive', false); compiler.internal.runtime.utils.setInstallerLocation('/app/matlab/MATLAB_Runtime_glnxa64.zip'); compiler.runtime.customInstaller('iquam_runtime', results, OutputDir='/tmp/runtime_installer', RuntimeDelivery='installer'); disp('Custom installer generated successfully');" || \
    (echo "ERROR: MATLAB build step failed for iquam." && echo "  This covers BOTH license checkout AND runtime-installer packaging." && echo "  'Invalid MATLAB Runtime installer' => the installer in the base image does" && echo "  not match the installed MATLAB; rebuild mur-matlab-base (its digest pin)." && echo "  A license-server timeout => check connectivity to the servers in network.lic." && exit 1) && \
    echo "Verifying compiled files:" && \
    ls -lh /tmp/iquam_build/

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
    zlib1g \
    wget \
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
    chmod +x iquam_runtime.install && \
    ./iquam_runtime.install -mode silent -agreeToLicense yes -destinationFolder /opt/matlabruntime && \
    rm -rf /tmp/runtime_installer

# Create application directory
RUN mkdir -p /opt/iquam/bin

# Copy compiled application and separate CTF file from builder stage
COPY --from=builder /tmp/iquam_build/IquamProcessor /opt/iquam/bin/
COPY --from=builder /tmp/iquam_build/run_IquamProcessor.sh /opt/iquam/bin/
COPY --from=builder /tmp/iquam_build/IquamProcessor.ctf /opt/iquam/bin/

# Make executable
RUN chmod +x /opt/iquam/bin/IquamProcessor /opt/iquam/bin/run_IquamProcessor.sh

# Set environment variables for MATLAB Runtime
ENV MCR_CACHE_ROOT=/tmp
ENV AGREE_TO_MATLAB_RUNTIME_LICENSE=yes
ENV MCR_INHIBIT_CTF_LOCK=1
ENV MATLAB_LOG_DIR=/data/logs
ENV MATLAB_PREFDIR=/tmp/.matlab
# HOME must point at a writable path so the MATLAB Runtime CTF extractor works
# when the container is run with an arbitrary --user <uid> that isn't present in
# /etc/passwd (getpwuid() returns NULL → default HOME of `/` is not writable).
ENV HOME=/tmp

# Create data directories. Scratch dirs under /tmp (/tmp/makebic, /tmp/.matlab,
# MCR cache) are NOT pre-created: the sticky bit on /tmp would otherwise block
# the runtime UID from rmdir'ing a root-owned dir from a prior layer. Letting
# the app create them at runtime means they're owned by the runtime UID and can
# be cleaned up by that same UID on subsequent runs.
RUN mkdir -p /data/output/iquam /data/cache/iquam /data/logs

# Set working directory
WORKDIR /data

# Entrypoint wrapper script (source: iquam/bin/entrypoint.sh).
# Dual-mode: accepts named args (--work-dir --log-dir --output-dir, for
# MAAP/OGC) or positional passthrough (for local docker run).
COPY iquam/bin/entrypoint.sh /opt/iquam/bin/entrypoint.sh
RUN chmod +x /opt/iquam/bin/entrypoint.sh

# Rootless / arbitrary-UID support (OpenShift pattern):
# Assign group 0 (root group) and grant group perms equal to owner perms on all
# paths the app may write to. Any UID added to group 0 at runtime (via
# `docker run --group-add 0`) can then read/write these paths.
# setgid on directories so new files/dirs inherit group 0.
RUN chgrp -R 0 /data /opt/iquam && \
    chmod -R g=u /data /opt/iquam && \
    find /data /opt/iquam -type d -exec chmod g+s {} +

# Set entrypoint
ENTRYPOINT ["/opt/iquam/bin/entrypoint.sh"]

# Labels for metadata
# org.opencontainers.image.source connects the pushed package to the
# repository on GHCR. Images are pushed by hand (no CI can reach the JPL
# licence servers), so without this label a package lands unlinked and has
# to be connected through the web UI.
LABEL org.opencontainers.image.source="https://github.com/podaac/mur"
LABEL description="IQUAM In-Situ SST Processing Module - NRT Mode"
LABEL version="1.1"
LABEL maintainer="MUR Team"
LABEL build-pattern="Multi-stage: MATLAB compilation → Base runtime image"
LABEL base-image="mur-matlab-base:r2024b"

# Performance Note: When running this container, use --shm-size=512M for optimal MATLAB Runtime performance
