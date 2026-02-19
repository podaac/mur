# MATLAB R2024b Base Builder Image with Compiler and Runtime Installer
#
# This base image is used by all MUR processing modules (iquam, l2p, landice, mrva)
# to avoid redundant MATLAB compiler installation and runtime downloads.
#
# Build:
#   cd mur/matlab-base
#   docker build --platform linux/amd64 -t mur-matlab-base:r2024b -f Dockerfile ..
#
FROM mathworks/matlab:r2024b

# Switch to root user for installations
USER root

# Create license directory and copy license file from parent context
# License file should exist at ../network.lic (relative to build context)
# Copy network.lic.example to network.lic before building
RUN mkdir -p /opt/matlab/licenses
COPY network.lic /opt/matlab/licenses/network.lic

# Set environment variable to point to license file
ENV MLM_LICENSE_FILE=/opt/matlab/licenses/network.lic

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
RUN ./mpm install \
    --release=r2024b \
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
RUN wget --progress=dot:giga -P /app/matlab/ \
    https://ssd.mathworks.com/supportfiles/downloads/R2024b/Release/6/deployment_files/installer/complete/glnxa64/MATLAB_Runtime_R2024b_Update_6_glnxa64.zip

# Labels for metadata
LABEL description="MUR MATLAB R2024b Base Builder Image with Compiler and Runtime Installer"
LABEL version="1.0"
LABEL matlab-release="R2024b"
LABEL matlab-update="Update 6"
LABEL maintainer="MUR Team"

# Default working directory
WORKDIR /app/matlab
