# LandIce Runtime Deployment Guide

## Overview
This guide explains how to deploy the compiled LandIce MATLAB application in a lightweight runtime container that only includes the MATLAB Runtime (MCR), not the full MATLAB installation.

The container uses fixed paths:
- `/input` - Mount your input data here (read-only)
- `/output` - Mount your output directory here
- Only `year` and `doy` arguments are required as positional parameters - the entrypoint automatically maps `/input` and `/output` directories

## Building Containers

**IMPORTANT:** The Dockerfile references shared utilities from the `../common` folder, so the build context must include the parent `mur` directory. Build from within the landice directory and set the context to the parent (`..`).

### Using Apple's Container Tools (macOS)
If you're on macOS and have Apple's container tools installed, you can build AMD64 containers using:

```bash
# Navigate to the landice directory
cd mur/landice

# Build for AMD64 architecture using Apple's container tool
container build --arch amd64 -f Dockerfile -t landice:latest ..

# Or build with Docker specifying the platform
docker build --platform linux/amd64 -f Dockerfile -t landice:latest ..
```

**Note:** The `..` at the end sets the build context to the parent `mur` directory, which allows the Dockerfile to access both `landice/` and `common/` folders. When building AMD64 containers on Apple Silicon Macs, the `--arch amd64` flag ensures the container is built for x86_64 architecture, which may be required for compatibility with production environments.

## Deployment Options

### Option 1: Multi-Stage Build (Recommended)
Build and deploy in a single Docker build process:

**⚠️ Important License Warning:**
The build process requires a valid MATLAB license server connection during compilation. If the license server is unreachable or the license cannot be obtained, the build may hang indefinitely at the compilation step. Ensure:
- Your network can reach the MATLAB license servers
- You have valid MATLAB and MATLAB Compiler licenses
- The `network.lic` file exists in the parent directory (copy from `network.lic.example`)

```bash
# Build the multi-stage container with Docker
cd mur/landice
docker build --platform linux/amd64 -f Dockerfile -t landice:latest ..

# Run the application
docker run --rm \
  --memory=4g \
  --memory-reservation=2g \
  --memory-swap=6g \
  --shm-size=512M \
  --cpus="2.0" \
  -e MCR_CACHE_ROOT=/tmp/mcr_cache \
  -e MCR_CACHE_SIZE=1024M \
  -e _JAVA_OPTIONS="-Xmx2048m -Xms512m -XX:+UseG1GC -XX:+UseStringDeduplication" \
  -e OSISAF_FTP_REPROCESSED="ftp://osisaf.met.no/reprocessed" \
  -e OSISAF_FTP_ARCHIVE="ftp://osisaf.met.no/archive" \
  -e OSISAF_FTP_PROD="ftp://osisaf.met.no/prod" \
  -v $(pwd)/tests/in:/input:ro \
  -v $(pwd)/tests/out:/output \
  landice:latest \
  2024 101
```

## Performance Optimization

### Shared Memory Configuration (Required)
MATLAB Runtime requires shared memory to be set to 512MB for optimal performance:
```bash
docker run --rm \
  --shm-size=512M \
  landice-runtime:latest [arguments]
```

### Memory Settings
For large datasets, adjust Docker memory limits:
```bash
docker run --rm \
  --shm-size=512M \
  --memory="4g" \
  --memory-swap="4g" \
  --cpus="2" \
  landice-runtime:latest [arguments]
```

### MCR Cache Settings
Optimize MATLAB Runtime cache:
```bash
docker run --rm \
  --shm-size=512M \
  -e MCR_CACHE_SIZE=2048M \
  -e MCR_CACHE_ROOT=/tmp/mcr_cache \
  -v /fast/storage/mcr_cache:/tmp/mcr_cache \
  landice-runtime:latest [arguments]
```

## Monitoring and Logging

### Enable Verbose Logging
```bash
docker run --rm \
  --shm-size=512M \
  -e MCR_CACHE_VERBOSE=true \
  landice-runtime:latest [arguments] 2>&1 | tee landice_$(date +%Y%m%d_%H%M%S).log
```

### Health Check Script
```bash
#!/bin/bash
# healthcheck.sh

docker run --rm landice-runtime:latest -? > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "LandIce container is healthy"
    exit 0
else
    echo "LandIce container health check failed"
    exit 1
fi
```

## Troubleshooting

### Common Issues and Solutions

1. **Build Hangs During Compilation**
   If the Docker build appears to hang at the `mcc` compilation step:
   ```bash
   # Check license server connectivity from your host
   telnet .....
   
   # Or test with a simpler MATLAB command first
   docker run --rm \
     -e MLM_LICENSE_FILE={PORT}@{SERVER} \
     mathworks/matlab:r2024b \
     -batch "disp('License check successful')"
   ```
   
   Common causes:
   - License server unreachable (network/firewall issues)
   - No available licenses
   - Incorrect license server configuration
   - VPN required for license server access

2. **Missing Libraries**
   ```bash
   # Check for missing libraries
   docker run --rm landice-runtime:latest ldd /opt/landice/bin/LandIce
   ```

2. **Permission Issues**
   ```bash
   # Ensure output directory is writable
   docker run --rm \
     --shm-size=512M \
     --user $(id -u):$(id -g) \
     -v /path/to/output:/output \
     landice-runtime:latest [arguments]
   ```

3. **Network Issues**
   ```bash
   # Test FTP connectivity
   docker run --rm landice-runtime:latest \
     bash -c "curl -I ftp://osisaf.met.no/"
   ```

4. **Memory Issues**
   Increase Docker memory allocation or use swap:
   ```bash
   docker run --rm \
     --shm-size=512M \
     --memory="8g" \
     --memory-swap="16g" \
     landice-runtime:latest [arguments]
   ```

## Security Considerations

1. **Run as Non-Root User**
   ```dockerfile
   # Add to Dockerfile.runtime
   RUN useradd -m -u 1000 landice
   USER landice
   ```

2. **Read-Only Root Filesystem**
   ```bash
   docker run --rm \
     --read-only \
     --tmpfs /tmp \
     landice-runtime:latest [arguments]
   ```

3. **Network Isolation**
   Use Docker networks to isolate containers:
   ```bash
   docker network create landice-net
   docker run --rm --network=landice-net landice-runtime:latest [arguments]
   ```