# Land Ice Operations - MATLAB Application

This MATLAB application automates landmask and ice operations for MUR SST input data. It processes data for two grid resolutions (`p01` at 0.01° and `p011` at 0.011°) using OSI SAF sea ice datasets and has been containerized for easy deployment.

---

## Overview

The application:
- Processes land ice operations for a specified year and day-of-year
- Handles both P01 and P011 grid resolutions automatically in each run
- Uses OSI SAF FTP endpoints for sea ice data access
- Compiled as a standalone MATLAB executable for containerized deployment
- No MATLAB license required to run the compiled version
- Uses fixed container paths for simplified deployment (`/input` and `/output`)
- Optimized with shared memory configuration for MATLAB Runtime performance

---

## Quick Start - Containerized Deployment (Recommended)

### Build and Run

**⚠️ Important:** The build process requires a valid MATLAB license server connection during compilation. If the license server is unreachable, the build may hang at the compilation step.

**IMPORTANT:** The Dockerfile references shared utilities from the `../common` folder, so the build context must include the parent `mur` directory. Build from within the landice directory and set the context to the parent (`..`).

```bash
# Navigate to the landice directory
cd mur/landice

# Build the container (AMD64 for production compatibility)
docker build --platform linux/amd64 -f Dockerfile.multistage -t landice:latest ..

# For macOS with Apple container tools:
# container build --arch amd64 -f Dockerfile.multistage -t landice:latest ..

# Run with simplified arguments
docker run --rm --shm-size=512M \
  -e OSISAF_FTP_REPROCESSED="ftp://osisaf.met.no/reprocessed" \
  -e OSISAF_FTP_ARCHIVE="ftp://osisaf.met.no/archive" \
  -e OSISAF_FTP_PROD="ftp://osisaf.met.no/prod" \
  -v /path/to/input:/input:ro \
  -v /path/to/output:/output \
  landice:latest \
  2024 100
```

### Container Features

- **Fixed paths**: Input data at `/input`, output at `/output` - just bind mount your directories
- **Simplified arguments**: Only `year` and `doy` required as positional parameters
- **Automatic processing**: Processes both P01 and P011 grids in a single run
- **Flexible MATLAB code**: The underlying MATLAB script can still accept any input/output paths for development
- **Optimized performance**: Requires `--shm-size=512M` for MATLAB Runtime (mandatory)
- **No license required**: Self-contained with MATLAB Runtime R2024b
- **Memory optimization**: Supports configurable memory limits and Java heap settings

---

## Requirements

### For Containerized Deployment
- Docker
- Input data directory 
- Output data directory

### For Development
- MATLAB R2024b with required toolboxes:
  - MATLAB Compiler
  - Control System Toolbox
- Access to MATLAB license server

---

## Usage Examples

### Basic Usage
```bash
# Process day 150 of 2024
docker run --rm --shm-size=512M \
  -v /data/input:/input:ro \
  -v /data/output:/output \
  landice:latest \
  2024 150
```

### With Custom OSI SAF Endpoints
```bash
docker run --rm --shm-size=512M \
  -e OSISAF_FTP_REPROCESSED="ftp://your-server/reprocessed" \
  -e OSISAF_FTP_ARCHIVE="ftp://your-server/archive" \
  -e OSISAF_FTP_PROD="ftp://your-server/prod" \
  -v /data/input:/input:ro \
  -v /data/output:/output \
  landice:latest \
  2024 150
```

### With Performance Optimization
```bash
docker run --rm \
  --memory=4g \
  --memory-reservation=2g \
  --memory-swap=6g \
  --shm-size=512M \
  --cpus="2.0" \
  -e MCR_CACHE_ROOT=/tmp/mcr_cache \
  -e MCR_CACHE_SIZE=1024M \
  -e _JAVA_OPTIONS="-Xmx2048m -Xms512m -XX:+UseG1GC" \
  -e OSISAF_FTP_REPROCESSED="ftp://osisaf.met.no/reprocessed" \
  -e OSISAF_FTP_ARCHIVE="ftp://osisaf.met.no/archive" \
  -e OSISAF_FTP_PROD="ftp://osisaf.met.no/prod" \
  -v /data/input:/input:ro \
  -v /data/output:/output \
  landice:latest \
  2024 150
```

## Batch Processing

For processing multiple days, create a simple bash script:

```bash
#!/bin/bash
YEAR=2024
START_DOY=1
END_DOY=365

for DOY in $(seq $START_DOY $END_DOY); do
    echo "Processing Year: $YEAR, DOY: $DOY"
    
    docker run --rm --shm-size=512M \
        -e OSISAF_FTP_REPROCESSED="ftp://osisaf.met.no/reprocessed" \
        -e OSISAF_FTP_ARCHIVE="ftp://osisaf.met.no/archive" \
        -e OSISAF_FTP_PROD="ftp://osisaf.met.no/prod" \
        -v /data/input:/input:ro \
        -v /data/output:/output \
        landice:latest \
        $YEAR $DOY
        
    if [ $? -ne 0 ]; then
        echo "Error processing Year: $YEAR, DOY: $DOY"
    fi
done
```

---

## Environment Variables

The application uses these environment variables for OSI SAF FTP access:

- `OSISAF_FTP_REPROCESSED`: FTP path for reprocessed data (default: ftp://osisaf.met.no/reprocessed)
- `OSISAF_FTP_ARCHIVE`: FTP path for archive data (default: ftp://osisaf.met.no/archive)  
- `OSISAF_FTP_PROD`: FTP path for production data (default: ftp://osisaf.met.no/prod)

---

## Directory Structure

```
landice/
├── src/
│   ├── landice_wrapper.m      # Main entry point (wrapper for CLI arguments)
│   ├── makeicefiles.m         # Ice file generation (core logic)
│   ├── readosisafice.m        # OSI SAF data reader and downloader
│   ├── setup_environment.m    # Environment setup
│   ├── julian.m               # Date conversion utilities
│   └── ...                    # Other utility MATLAB files
├── data_creation/
│   ├── p01/                   # P01 grid resolution files (0.01°)
│   │   ├── saf2north.m        # North region mapping
│   │   └── saf2south.m        # South region mapping
│   └── p011/                  # P011 grid resolution files (0.011°)
│       ├── saf2north.m        # North region mapping
│       └── saf2south.m        # South region mapping
├── tests/
│   ├── in/                    # Test input data
│   └── out/                   # Test output data
├── Dockerfile.multistage      # Multi-stage build (recommended)
├── Dockerfile.matlab          # Development container
├── Dockerfile.runtime         # Runtime-only container
├── BUILD_INSTRUCTIONS.md      # Detailed build instructions
└── DEPLOYMENT.md              # Production deployment guide
```

---

## Documentation

- **[BUILD_INSTRUCTIONS.md](BUILD_INSTRUCTIONS.md)** - Complete build instructions for development
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Production deployment guide with Docker Compose and Kubernetes examples

---

## Production Deployment

### Docker Compose

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  landice:
    image: landice:latest
    environment:
      - OSISAF_FTP_REPROCESSED=${OSISAF_FTP_REPROCESSED}
      - OSISAF_FTP_ARCHIVE=${OSISAF_FTP_ARCHIVE}
      - OSISAF_FTP_PROD=${OSISAF_FTP_PROD}
    volumes:
      - ${INPUT_DIR}:/input:ro
      - ${OUTPUT_DIR}:/output
    command: ["${YEAR}", "${DOY}"]
    shm_size: '512m'
```

### Kubernetes

Deploy as a Job:
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: landice-processor
spec:
  template:
    spec:
      containers:
      - name: landice
        image: landice:latest
        args: ["2024", "100"]
        env:
        - name: OSISAF_FTP_REPROCESSED
          value: "ftp://osisaf.met.no/reprocessed"
        volumeMounts:
        - name: input-data
          mountPath: /input
          readOnly: true
        - name: output-data
          mountPath: /output
        resources:
          requests:
            memory: "2Gi"
            cpu: "1"
          limits:
            memory: "4Gi"
            cpu: "2"
      restartPolicy: OnFailure
```

---

## Troubleshooting

### Build Issues

**Build hangs during compilation:**
- Check MATLAB license server connectivity
- Ensure valid MATLAB Compiler license is available
- Verify network access to license servers (may require VPN)

### Runtime Issues

**Memory errors:**
```bash
# Increase memory allocation
docker run --rm \
  --shm-size=512M \
  --memory="8g" \
  --memory-swap="16g" \
  landice:latest 2024 100
```

**Permission issues:**
```bash
# Run with user permissions
docker run --rm \
  --shm-size=512M \
  --user $(id -u):$(id -g) \
  -v /path/to/output:/output \
  landice:latest 2024 100
```

---

## Resolution Notes

The landice container generates two grid resolutions per run:

| Resolution | Grid | Output directory | Filename pattern | Used by |
| --- | --- | --- | --- | --- |
| **p01** (0.01°) | `maskGLOBp01deg.gds` | `land/p01/YYYY/` | `landiceP01_YYYY_DDD.gds.gz` | **MUR v4** (current) |
| **p011** (0.011°/~1km) | `maskGlob1km.gds` | `land/p011/YYYY/` | `landice_YYYY_DDD.gds.gz` | MUR v3 (legacy, not used) |

**Only p01 output is used by the current MUR v4 pipeline.** The p011 resolution is a legacy artifact from MUR v3 (0.011° product). The MRVA container mounts only the `land/p01/` subdirectory and expects `landiceP01_` prefixed filenames. The p011 output is generated but not consumed by any current processing stage.

In the original production system, both resolutions were written to the same flat directory (`/nas2/landice/YYYY/`), so the `P01` filename prefix was necessary to distinguish them. In the containerized setup, they are separated into `land/p01/` and `land/p011/` subdirectories, making the prefix redundant — but it is retained for compatibility with the MRVA MATLAB code that expects it.

---

## General Notes

- Execution time is logged for monitoring purposes
- Container uses MATLAB Runtime R2024b - no MATLAB license required for execution
- Shared memory (`--shm-size=512M`) is mandatory for MATLAB Runtime
- Input directory should contain the required MUR SST data files
- Output directory will contain the processed land ice files
