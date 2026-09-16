# MATLAB R2024b Base Builder Image with Compiler and Runtime Installer
#
# This base image is used by all MUR processing modules (iquam, l2p, landice, mrva)
# to avoid redundant MATLAB compiler installation and runtime downloads.
#
# Build:
#   cd mur/matlab-base
#   docker build --platform linux/amd64 -t mur-matlab-base:r2024b -f Dockerfile ..
#
# ---------------------------------------------------------------------------
# PINNED BY DIGEST -- do not replace with a bare tag.
#
# The `r2024b` tag floats: MathWorks rebuilds it periodically, and the upstream
# Dockerfile runs its own `mpm install --release=R2024b` UNPINNED into
# /opt/matlab/R2024b. A rebuild therefore silently bumps the MATLAB update
# level, which used to break the Runtime installer match below with the
# unhelpful error "Invalid MATLAB Runtime installer".
#
# Digest resolved 2026-09-15; tag was last rebuilt 2026-09-14.
# To move to a newer update, re-resolve the digest and rebuild -- everything
# else below follows from it automatically.
# ---------------------------------------------------------------------------
ARG MATLAB_IMAGE_DIGEST=sha256:39532fb0f97bfae28a95c4341b9ddbb7527cf7ee2fa56d144d1439df9c32234f
FROM mathworks/matlab:r2024b@${MATLAB_IMAGE_DIGEST}

# Optional assertion. Leave empty to accept whatever update the pinned digest
# carries; set it (e.g. --build-arg EXPECT_MATLAB_UPDATE=10) to make the
# expected update explicit and fail the build if the digest ever disagrees.
ARG EXPECT_MATLAB_UPDATE=

# Switch to root user for installations
USER root

# Create license directory and copy license file from parent context
# License file should exist at ../network.lic (relative to build context)
# Copy network.lic.example to network.lic before building
RUN mkdir -p /opt/matlab/licenses
COPY network.lic /opt/matlab/licenses/network.lic

# Set environment variable to point to license file
ENV MLM_LICENSE_FILE=/opt/matlab/licenses/network.lic

# ---------------------------------------------------------------------------
# Resolve the MATLAB update level from the installation the pinned digest
# carries. Every version-sensitive step below derives from this single value,
# so the compiler, the toolboxes and the Runtime installer cannot drift apart.
# ---------------------------------------------------------------------------
RUN set -eu; \
    vinfo=/opt/matlab/R2024b/VersionInfo.xml; \
    update=$(sed -n 's:.*<description>Update \([0-9][0-9]*\)</description>.*:\1:p' "$vinfo"); \
    if [ -z "$update" ]; then \
        echo "ERROR: could not determine the MATLAB update level from $vinfo." >&2; \
        echo "       Expected a <description>Update N</description> element:" >&2; \
        cat "$vinfo" >&2; \
        exit 1; \
    fi; \
    if [ -n "${EXPECT_MATLAB_UPDATE}" ] && [ "${EXPECT_MATLAB_UPDATE}" != "$update" ]; then \
        echo "ERROR: pinned image carries MATLAB R2024b Update $update," >&2; \
        echo "       but EXPECT_MATLAB_UPDATE=${EXPECT_MATLAB_UPDATE} was requested." >&2; \
        echo "       Re-resolve MATLAB_IMAGE_DIGEST or update the expectation." >&2; \
        exit 1; \
    fi; \
    echo "$update" > /opt/matlab/.update_level; \
    echo "Resolved MATLAB R2024b Update $update"; \
    cat "$vinfo"

# Install build dependencies including unzip for runtime installer
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    make \
    wget \
    curl \
    unzip \
    gzip \
    bzip2 \
    && rm -rf /var/lib/apt/lists/*

# Create directory and download MATLAB Package Manager (mpm)
WORKDIR /tmp/mpm
RUN wget -q https://www.mathworks.com/mpm/glnxa64/mpm \
    && chmod +x mpm

# Install MATLAB Compiler and toolboxes (needed by MRVA)
# --release must match the update already installed at this destination; mpm is
# ADDING products to the upstream installation, not creating a new one.
RUN update=$(cat /opt/matlab/.update_level) && \
    ./mpm install \
    --release=R2024bU${update} \
    --destination=/opt/matlab/R2024b \
    --products MATLAB \
    MATLAB_Compiler \
    Image_Processing_Toolbox \
    Statistics_and_Machine_Learning_Toolbox

# Set MATLAB path
ENV PATH="/opt/matlab/R2024b/bin:${PATH}"

# Switch to matlab user for runtime download (doesn't need root)
USER matlab

# Create MATLAB application directory
WORKDIR /app/matlab
USER root
RUN chown -R matlab:matlab /app/matlab
USER matlab

# Download MATLAB Runtime installer (shared by all modules)
# This is the largest download and benefits most from caching
# Downloaded to a STABLE path (/app/matlab/MATLAB_Runtime_glnxa64.zip) so the
# module Dockerfiles reference one filename regardless of update level.
# Verified with `unzip -t`: a truncated or error-page download otherwise shows
# up much later as "Invalid MATLAB Runtime installer".
RUN set -eu; \
    update=$(cat /opt/matlab/.update_level); \
    url="https://ssd.mathworks.com/supportfiles/downloads/R2024b/Release/${update}/deployment_files/installer/complete/glnxa64/MATLAB_Runtime_R2024b_Update_${update}_glnxa64.zip"; \
    echo "Downloading MATLAB Runtime installer for Update ${update}"; \
    wget --progress=dot:giga -O /app/matlab/MATLAB_Runtime_glnxa64.zip "$url"; \
    unzip -tq /app/matlab/MATLAB_Runtime_glnxa64.zip >/dev/null \
      || { echo "ERROR: downloaded Runtime installer is not a valid zip." >&2; exit 1; }; \
    echo "Runtime installer verified."

# Record what was actually resolved, for `docker inspect`.
RUN echo "MATLAB update level:" && cat /opt/matlab/.update_level

# Labels for metadata
LABEL description="MUR MATLAB R2024b Base Builder Image with Compiler and Runtime Installer"
LABEL version="1.0"
LABEL matlab-release="R2024b"
LABEL matlab-update="derived from pinned digest; see /opt/matlab/.update_level"
LABEL maintainer="MUR Team"

# Default working directory
WORKDIR /app/matlab
