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
    timeout 600s matlab -batch "results = compiler.build.standaloneApplication('landice_wrapper.m', 'TreatInputsAsNumeric', 'off', 'OutputDir', '/tmp/landice_build', 'ExecutableName', 'LandiceProcessor', 'EmbedArchive', false); compiler.internal.runtime.utils.setInstallerLocation('/app/matlab/MATLAB_Runtime_glnxa64.zip'); compiler.runtime.customInstaller('landice_runtime', results, OutputDir='/tmp/runtime_installer', RuntimeDelivery='installer'); disp('Custom installer generated successfully');" || \
    (echo "ERROR: MATLAB build step failed for landice." && echo "  This covers BOTH license checkout AND runtime-installer packaging." && echo "  'Invalid MATLAB Runtime installer' => the installer in the base image does" && echo "  not match the installed MATLAB; rebuild mur-matlab-base (its digest pin)." && echo "  A license-server timeout => check connectivity to the servers in network.lic." && exit 1) && \
    echo "Verifying compiled files:" && \
    ls -lh /tmp/landice_build/

# ========================================================================
# Stage 2: Minimal Debian runtime stage with custom MATLAB Runtime
# ========================================================================
FROM debian:bookworm-slim

# Install runtime dependencies including Python3
# libxt6, libxmu6: Required by MATLAB Runtime for X11 components even in headless mode
# awscli: used by common/bin/localize.sh (sourced by entrypoint.sh below) to
# fetch s3:// input hrefs to local disk before MATLAB runs -- see
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
# HOME must point at a writable path so the MATLAB Runtime CTF extractor works
# when the container is run with an arbitrary --user <uid> that isn't present in
# /etc/passwd (getpwuid() returns NULL → default HOME of `/` is not writable).
ENV HOME=/tmp

# Environment variables for OSI SAF FTP paths (to be overridden at runtime)
ENV OSISAF_FTP_REPROCESSED=""
ENV OSISAF_FTP_ARCHIVE=""
ENV OSISAF_FTP_PROD=""

# Create data directories. Scratch dirs under /tmp (/tmp/landice_tmp,
# /tmp/.matlab, MCR cache) are NOT pre-created: the sticky bit on /tmp would
# otherwise block the runtime UID from rmdir'ing a root-owned dir. Letting the
# app create them at runtime means they're owned by the runtime UID.
RUN mkdir -p /data/input /data/output/p011 /data/output/p01 /data/logs

# Set working directory
WORKDIR /data

# Shared input-localization helper (source: common/bin/localize.sh), sourced
# by entrypoint.sh below. Copied into the runtime stage directly -- unlike
# common/*.m above, this is bash, not MATLAB source to be compiled away, so
# it has to persist into this final image rather than living only in the
# builder stage.
COPY common/bin/localize.sh /opt/common/bin/localize.sh
RUN chmod +x /opt/common/bin/localize.sh

# Entrypoint wrapper script (source: landice/bin/entrypoint.sh).
# Named-args only (--year --doy plus the six --*-file flags); each file flag
# accepts either a local path or an s3:// href, resolved via localize.sh.
COPY landice/bin/entrypoint.sh /opt/landice/bin/entrypoint.sh
RUN chmod +x /opt/landice/bin/entrypoint.sh

# Rootless / arbitrary-UID support (OpenShift pattern):
# Assign group 0 (root group) and grant group perms equal to owner perms on all
# paths the app may write to. Any UID added to group 0 at runtime (via
# `docker run --group-add 0`) can then read/write these paths.
# setgid on directories so new files/dirs inherit group 0.
RUN chgrp -R 0 /data /opt/landice && \
    chmod -R g=u /data /opt/landice && \
    find /data /opt/landice -type d -exec chmod g+s {} +

# Set entrypoint
ENTRYPOINT ["/opt/landice/bin/entrypoint.sh"]

# Default command shows help/usage by providing no arguments (will error with usage info)
CMD []

# Labels for metadata
# org.opencontainers.image.source connects the pushed package to the
# repository on GHCR. Images are pushed by hand (no CI can reach the JPL
# licence servers), so without this label a package lands unlinked and has
# to be connected through the web UI.
LABEL org.opencontainers.image.source="https://github.com/podaac/mur"
LABEL description="MUR LANDICE Processing Module - Container Wrapper"
LABEL version="2.1"
LABEL maintainer="MUR Team"
LABEL build-pattern="Multi-stage: MATLAB compilation → Base runtime image"
LABEL base-image="mur-matlab-base:r2024b"

# Performance Note: When running this container, use --shm-size=512M for optimal MATLAB Runtime performance