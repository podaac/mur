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
- Takes every static input file as an explicit named flag — no directory is bind-mounted whole and scanned; the calling orchestrator (`run_mur_pipeline.py` locally, `run_mur_maap.py` on MAAP) resolves and passes each of the six static files individually
- Each `--*-file` flag value may be either a local filesystem path (local `docker run`, bind-mounted) or an `s3://` href (MAAP, or any environment with S3 access) — the container fetches `s3://` values to local scratch space itself before MATLAB runs, so the same image works unchanged in either environment (see [Container Features](#container-features) below)
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
docker build --platform linux/amd64 -f Dockerfile -t mur-landice:latest ..

# For macOS with Apple container tools:
# container build --arch amd64 -f Dockerfile -t mur-landice:latest ..

# Run — every static input is an explicit flag, bind-mounted individually
docker run --rm --shm-size=512M \
  -e OSISAF_FTP_REPROCESSED="ftp://osisaf.met.no/reprocessed" \
  -e OSISAF_FTP_ARCHIVE="ftp://osisaf.met.no/archive" \
  -e OSISAF_FTP_PROD="ftp://osisaf.met.no/prod" \
  -v /path/to/static-resources/grids/maskGLOBp01deg.gds:/input/landmask-p01.gds:ro \
  -v /path/to/static-resources/mat/p01/saf2north.mat:/input/gridindex-north-p01.mat:ro \
  -v /path/to/static-resources/mat/p01/saf2south.mat:/input/gridindex-south-p01.mat:ro \
  -v /path/to/static-resources/grids/maskGlob1km.gds:/input/landmask-p011.gds:ro \
  -v /path/to/static-resources/mat/p011/saf2north.mat:/input/gridindex-north-p011.mat:ro \
  -v /path/to/static-resources/mat/p011/saf2south.mat:/input/gridindex-south-p011.mat:ro \
  -v /path/to/output/p011:/output/p011 \
  -v /path/to/output/p01:/output/p01 \
  mur-landice:latest \
  --year 2024 --doy 100 \
  --landmask-p01-file /input/landmask-p01.gds \
  --gridindex-north-p01-file /input/gridindex-north-p01.mat \
  --gridindex-south-p01-file /input/gridindex-south-p01.mat \
  --landmask-p011-file /input/landmask-p011.gds \
  --gridindex-north-p011-file /input/gridindex-north-p011.mat \
  --gridindex-south-p011-file /input/gridindex-south-p011.mat
```

See [documentation/STATIC_DATA.md](../documentation/STATIC_DATA.md) for where the six static files (`grids/maskGLOBp01deg.gds`, `mat/p01/saf2north.mat`, etc.) come from and their full-tree layout.

### Container Features

- **Explicit named inputs**: every static file (landmask + grid-index files, both resolutions) is its own `--flag`; there is no directory mount to scan
- **Named args only**: `--year`/`--doy` plus the six file flags — no positional-argument form is accepted
- **Local-path or S3-href inputs, uniformly**: `entrypoint.sh` sources the shared `common/bin/localize.sh` helper and resolves each of the six file flags before MATLAB runs — a value starting with `s3://` is fetched to local scratch space (via `aws s3 cp`) and the local path substituted; any other value is assumed to already be a local path (e.g. a bind mount) and passed through unchanged. AWS credentials come from the standard AWS credential chain — environment variables (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`) for local dev, an IAM role automatically when running on AWS/MAAP compute — no extra flags or config needed either way.
- **Automatic processing**: Processes both P01 and P011 grids in a single run
- **Optimized performance**: Requires `--shm-size=512M` for MATLAB Runtime (mandatory)
- **No license required**: Self-contained with MATLAB Runtime R2024b
- **Memory optimization**: Supports configurable memory limits and Java heap settings

---

## Requirements

### For Containerized Deployment
- Docker
- The six static input files (see [documentation/STATIC_DATA.md](../documentation/STATIC_DATA.md))
- Output directories (one per resolution: `p011`, `p01`)

### For Development
- MATLAB R2024b with MATLAB Compiler
- Access to MATLAB license server

---

## Usage Examples

### Basic Usage
```bash
# Process day 150 of 2024
docker run --rm --shm-size=512M \
  -v /data/static-resources/grids/maskGLOBp01deg.gds:/input/landmask-p01.gds:ro \
  -v /data/static-resources/mat/p01/saf2north.mat:/input/gridindex-north-p01.mat:ro \
  -v /data/static-resources/mat/p01/saf2south.mat:/input/gridindex-south-p01.mat:ro \
  -v /data/static-resources/grids/maskGlob1km.gds:/input/landmask-p011.gds:ro \
  -v /data/static-resources/mat/p011/saf2north.mat:/input/gridindex-north-p011.mat:ro \
  -v /data/static-resources/mat/p011/saf2south.mat:/input/gridindex-south-p011.mat:ro \
  -v /data/output/p011:/output/p011 \
  -v /data/output/p01:/output/p01 \
  mur-landice:latest \
  --year 2024 --doy 150 \
  --landmask-p01-file /input/landmask-p01.gds \
  --gridindex-north-p01-file /input/gridindex-north-p01.mat \
  --gridindex-south-p01-file /input/gridindex-south-p01.mat \
  --landmask-p011-file /input/landmask-p011.gds \
  --gridindex-north-p011-file /input/gridindex-north-p011.mat \
  --gridindex-south-p011-file /input/gridindex-south-p011.mat
```

### With Custom OSI SAF Endpoints
```bash
docker run --rm --shm-size=512M \
  -e OSISAF_FTP_REPROCESSED="ftp://your-server/reprocessed" \
  -e OSISAF_FTP_ARCHIVE="ftp://your-server/archive" \
  -e OSISAF_FTP_PROD="ftp://your-server/prod" \
  -v /data/static-resources/grids/maskGLOBp01deg.gds:/input/landmask-p01.gds:ro \
  -v /data/static-resources/mat/p01/saf2north.mat:/input/gridindex-north-p01.mat:ro \
  -v /data/static-resources/mat/p01/saf2south.mat:/input/gridindex-south-p01.mat:ro \
  -v /data/static-resources/grids/maskGlob1km.gds:/input/landmask-p011.gds:ro \
  -v /data/static-resources/mat/p011/saf2north.mat:/input/gridindex-north-p011.mat:ro \
  -v /data/static-resources/mat/p011/saf2south.mat:/input/gridindex-south-p011.mat:ro \
  -v /data/output/p011:/output/p011 \
  -v /data/output/p01:/output/p01 \
  mur-landice:latest \
  --year 2024 --doy 150 \
  --landmask-p01-file /input/landmask-p01.gds \
  --gridindex-north-p01-file /input/gridindex-north-p01.mat \
  --gridindex-south-p01-file /input/gridindex-south-p01.mat \
  --landmask-p011-file /input/landmask-p011.gds \
  --gridindex-north-p011-file /input/gridindex-north-p011.mat \
  --gridindex-south-p011-file /input/gridindex-south-p011.mat
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
  -v /data/static-resources/grids/maskGLOBp01deg.gds:/input/landmask-p01.gds:ro \
  -v /data/static-resources/mat/p01/saf2north.mat:/input/gridindex-north-p01.mat:ro \
  -v /data/static-resources/mat/p01/saf2south.mat:/input/gridindex-south-p01.mat:ro \
  -v /data/static-resources/grids/maskGlob1km.gds:/input/landmask-p011.gds:ro \
  -v /data/static-resources/mat/p011/saf2north.mat:/input/gridindex-north-p011.mat:ro \
  -v /data/static-resources/mat/p011/saf2south.mat:/input/gridindex-south-p011.mat:ro \
  -v /data/output/p011:/output/p011 \
  -v /data/output/p01:/output/p01 \
  mur-landice:latest \
  --year 2024 --doy 150 \
  --landmask-p01-file /input/landmask-p01.gds \
  --gridindex-north-p01-file /input/gridindex-north-p01.mat \
  --gridindex-south-p01-file /input/gridindex-south-p01.mat \
  --landmask-p011-file /input/landmask-p011.gds \
  --gridindex-north-p011-file /input/gridindex-north-p011.mat \
  --gridindex-south-p011-file /input/gridindex-south-p011.mat
```

## Batch Processing

For processing multiple days, create a simple bash script:

```bash
#!/bin/bash
YEAR=2024
START_DOY=1
END_DOY=365
STATIC=/data/static-resources

for DOY in $(seq $START_DOY $END_DOY); do
    echo "Processing Year: $YEAR, DOY: $DOY"

    docker run --rm --shm-size=512M \
        -e OSISAF_FTP_REPROCESSED="ftp://osisaf.met.no/reprocessed" \
        -e OSISAF_FTP_ARCHIVE="ftp://osisaf.met.no/archive" \
        -e OSISAF_FTP_PROD="ftp://osisaf.met.no/prod" \
        -v "$STATIC/grids/maskGLOBp01deg.gds:/input/landmask-p01.gds:ro" \
        -v "$STATIC/mat/p01/saf2north.mat:/input/gridindex-north-p01.mat:ro" \
        -v "$STATIC/mat/p01/saf2south.mat:/input/gridindex-south-p01.mat:ro" \
        -v "$STATIC/grids/maskGlob1km.gds:/input/landmask-p011.gds:ro" \
        -v "$STATIC/mat/p011/saf2north.mat:/input/gridindex-north-p011.mat:ro" \
        -v "$STATIC/mat/p011/saf2south.mat:/input/gridindex-south-p011.mat:ro" \
        -v /data/output/p011:/output/p011 \
        -v /data/output/p01:/output/p01 \
        mur-landice:latest \
        --year "$YEAR" --doy "$DOY" \
        --landmask-p01-file /input/landmask-p01.gds \
        --gridindex-north-p01-file /input/gridindex-north-p01.mat \
        --gridindex-south-p01-file /input/gridindex-south-p01.mat \
        --landmask-p011-file /input/landmask-p011.gds \
        --gridindex-north-p011-file /input/gridindex-north-p011.mat \
        --gridindex-south-p011-file /input/gridindex-south-p011.mat

    if [ $? -ne 0 ]; then
        echo "Error processing Year: $YEAR, DOY: $DOY"
    fi
done
```

In practice, `run_mur_pipeline.py` already does this per-day looping and flag construction for you — see the main [README.md](../README.md#production-style-pipeline-orchestrator).

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
│   ├── landice_wrapper.m      # Compiled entry point — accepts the six explicit static file paths
│   ├── makeicefiles.m         # Ice file generation (core logic)
│   ├── readosisafice.m        # OSI SAF data reader and downloader
│   └── setup_environment.m    # Environment setup
├── bin/
│   └── entrypoint.sh          # Named-args-only container entrypoint; localizes s3:// inputs before invoking MATLAB
├── tests/
│   ├── test_entrypoint.sh     # Entrypoint argument-parsing + localization unit tests
│   ├── in/, out/               # Test fixtures
│   └── compare_outputs.py, validate_containerized.sh, test_execute_landice.py
├── Dockerfile                 # Multi-stage build (MATLAB compiler → runtime-only image, includes AWS CLI)
├── BUILD_INSTRUCTIONS.md      # Detailed build instructions
├── DEPLOYMENT.md              # Production deployment guide
└── REPROCESSING_DATES_README.md

../common/
├── bin/
│   └── localize.sh            # Shared s3://-or-local-path resolver, sourced by entrypoint.sh (also used by other containers as they're converted)
└── *.m                        # Shared MATLAB utilities (compiled into the MATLAB build stage)
```

---

## Documentation

- **[BUILD_INSTRUCTIONS.md](BUILD_INSTRUCTIONS.md)** - Complete build instructions for development
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Production deployment guide with Docker Compose and Kubernetes examples
- **[../documentation/STATIC_DATA.md](../documentation/STATIC_DATA.md)** - Where the six static input files live and how they're laid out

---

## Production Deployment

### Docker Compose

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  landice:
    image: mur-landice:latest
    environment:
      - OSISAF_FTP_REPROCESSED=${OSISAF_FTP_REPROCESSED}
      - OSISAF_FTP_ARCHIVE=${OSISAF_FTP_ARCHIVE}
      - OSISAF_FTP_PROD=${OSISAF_FTP_PROD}
    volumes:
      - ${STATIC_RESOURCES_DIR}/grids/maskGLOBp01deg.gds:/input/landmask-p01.gds:ro
      - ${STATIC_RESOURCES_DIR}/mat/p01/saf2north.mat:/input/gridindex-north-p01.mat:ro
      - ${STATIC_RESOURCES_DIR}/mat/p01/saf2south.mat:/input/gridindex-south-p01.mat:ro
      - ${STATIC_RESOURCES_DIR}/grids/maskGlob1km.gds:/input/landmask-p011.gds:ro
      - ${STATIC_RESOURCES_DIR}/mat/p011/saf2north.mat:/input/gridindex-north-p011.mat:ro
      - ${STATIC_RESOURCES_DIR}/mat/p011/saf2south.mat:/input/gridindex-south-p011.mat:ro
      - ${OUTPUT_DIR_P011}:/output/p011
      - ${OUTPUT_DIR_P01}:/output/p01
    command:
      - "--year"
      - "${YEAR}"
      - "--doy"
      - "${DOY}"
      - "--landmask-p01-file"
      - "/input/landmask-p01.gds"
      - "--gridindex-north-p01-file"
      - "/input/gridindex-north-p01.mat"
      - "--gridindex-south-p01-file"
      - "/input/gridindex-south-p01.mat"
      - "--landmask-p011-file"
      - "/input/landmask-p011.gds"
      - "--gridindex-north-p011-file"
      - "/input/gridindex-north-p011.mat"
      - "--gridindex-south-p011-file"
      - "/input/gridindex-south-p011.mat"
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
        image: mur-landice:latest
        args:
          - "--year"
          - "2024"
          - "--doy"
          - "100"
          - "--landmask-p01-file"
          - "/input/landmask-p01.gds"
          - "--gridindex-north-p01-file"
          - "/input/gridindex-north-p01.mat"
          - "--gridindex-south-p01-file"
          - "/input/gridindex-south-p01.mat"
          - "--landmask-p011-file"
          - "/input/landmask-p011.gds"
          - "--gridindex-north-p011-file"
          - "/input/gridindex-north-p011.mat"
          - "--gridindex-south-p011-file"
          - "/input/gridindex-south-p011.mat"
        env:
        - name: OSISAF_FTP_REPROCESSED
          value: "ftp://osisaf.met.no/reprocessed"
        volumeMounts:
        - name: static-resources
          mountPath: /input
          readOnly: true
        - name: output-p011
          mountPath: /output/p011
        - name: output-p01
          mountPath: /output/p01
        resources:
          requests:
            memory: "2Gi"
            cpu: "1"
          limits:
            memory: "4Gi"
            cpu: "2"
      restartPolicy: OnFailure
```

(The example mounts a directory at `/input` for brevity here — in practice each `--*-file` flag should point at an individually-mounted file, matching the `docker run` examples above, so nothing inside the container ever scans a directory to find its inputs.)

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
# Increase memory allocation (append to any of the examples above)
docker run --rm \
  --shm-size=512M \
  --memory="8g" \
  --memory-swap="16g" \
  ... \
  mur-landice:latest \
  --year 2024 --doy 100 \
  --landmask-p01-file /input/landmask-p01.gds \
  --gridindex-north-p01-file /input/gridindex-north-p01.mat \
  --gridindex-south-p01-file /input/gridindex-south-p01.mat \
  --landmask-p011-file /input/landmask-p011.gds \
  --gridindex-north-p011-file /input/gridindex-north-p011.mat \
  --gridindex-south-p011-file /input/gridindex-south-p011.mat
```

**Permission issues:**
```bash
# Run with user permissions
docker run --rm \
  --shm-size=512M \
  --user $(id -u):$(id -g) \
  ... \
  mur-landice:latest \
  --year 2024 --doy 100 \
  --landmask-p01-file /input/landmask-p01.gds \
  --gridindex-north-p01-file /input/gridindex-north-p01.mat \
  --gridindex-south-p01-file /input/gridindex-south-p01.mat \
  --landmask-p011-file /input/landmask-p011.gds \
  --gridindex-north-p011-file /input/gridindex-north-p011.mat \
  --gridindex-south-p011-file /input/gridindex-south-p011.mat
```

**Missing/unknown-flag errors:** all nine flags (`--year`, `--doy`, and the six `--*-file` flags) are required — positional arguments are no longer accepted. Run `docker run --rm mur-landice:latest` with no arguments to see the usage message.

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
- Every static input is passed as its own bind-mounted file and named flag — nothing is discovered by scanning a directory
- Each of the two output directories (`p011`, `p01`) will contain the processed land ice files for that resolution
