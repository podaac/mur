# MUR Pipeline Configuration and Operation

## Introduction

This document describes how to install, configure, and run the MUR preprocessing pipeline. It covers environment setup, container builds, configuration files, command-line operation, and troubleshooting.

**Note:** This documentation covers the preprocessing components. The final MRVA analysis and NetCDF output generation steps are currently in development and will be documented in a future update.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Container Setup](#container-setup)
4. [Configuration](#configuration)
5. [Running the Pipeline](#running-the-pipeline)
6. [Component-Specific Execution](#component-specific-execution)
7. [Monitoring and Logging](#monitoring-and-logging)
8. [Production Deployment](#production-deployment)
9. [Troubleshooting](#troubleshooting)

## Prerequisites

### System Requirements

**Minimum:**
- **CPU:** 4 cores
- **RAM:** 16 GB
- **Disk:** 500 GB fast storage (SSD recommended)
- **OS:** Linux (Ubuntu 20.04+, CentOS 8+) or macOS

**Recommended:**
- **CPU:** 16+ cores (for parallel sensor processing)
- **RAM:** 32+ GB
- **Disk:** 2+ TB (1 TB fast SSD + bulk storage)
- **Network:** 100 Mbps+ (for PO.DAAC downloads)

### Software Dependencies

**Required:**

1. **Docker**
   ```bash
   # Install Docker (Ubuntu/Debian)
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER  # Add user to docker group
   newgrp docker  # Apply group change

   # Verify installation
   docker --version
   docker run hello-world
   ```

2. **uv** (Python package and environment manager)
   ```bash
   # Install uv
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Add to PATH (add to ~/.bashrc or ~/.zshrc)
   export PATH="$HOME/.cargo/bin:$PATH"

   # Verify installation
   uv --version
   ```

3. **Python 3.11+**
   - Usually installed with uv
   - Check: `python3 --version`

**Optional:**

- **git** - For cloning repository
- **tmux** or **screen** - For long-running processes
- **htop** - For monitoring resource usage

### Data Access Credentials

**NASA Earthdata Login (Required for L2P data):**

1. Register for free account:
   - URL: https://urs.earthdata.nasa.gov/

2. Approve PO.DAAC application:
   - URL: https://urs.earthdata.nasa.gov/approve_app?client_id=BO_n7nTIlMljdvU6kRRB3g

3. Create `.netrc` file:
   ```bash
   touch ~/.netrc
   chmod 600 ~/.netrc

   cat > ~/.netrc << 'EOF'
   machine urs.earthdata.nasa.gov
       login YOUR_EARTHDATA_USERNAME
       password YOUR_EARTHDATA_PASSWORD
   EOF
   ```

**Verify credentials:**
```bash
curl -n https://podaac.jpl.nasa.gov/  # Should not prompt for login
```

## Installation

### Clone Repository

```bash
# Clone the MUR repository
git clone https://github.com/nasa-jpl/mur.git
cd mur
```

### Setup Python Environment

```bash
# Navigate to mur directory
cd mur/

# Sync environment (creates .venv and installs dependencies)
uv sync

# This creates:
#   - .venv/ directory with Python environment
#   - Installs all dependencies from pyproject.toml
#   - Creates command shortcuts (mur-pipeline, mur-viewer)
```

### Activate Environment (Optional)

```bash
# Option 1: Activate manually
source .venv/bin/activate

# Now you can use commands directly:
mur-pipeline --help
mur-viewer --help

# Option 2: Use 'uv run' prefix (no activation needed)
uv run mur-pipeline --help
uv run mur-viewer --help
```

**Note:** `uv run` automatically manages the environment, so activation is optional.

### Verify Installation

```bash
# Check Python environment
uv run python --version  # Should show Python 3.11+

# Check installed packages
uv pip list

# Test pipeline help
uv run mur-pipeline --help
```

## Container Setup

### Build All Containers

**Build from mur/ directory:**

```bash
# Land/Ice container
cd landice/
docker build --platform linux/amd64 -t mur-landice:latest -f Dockerfile ..
cd ..

# iQUAM buoy container
cd iquam/
docker build --platform linux/amd64 -t mur-iquam:latest -f Dockerfile ..
cd ..

# L2P satellite container
cd l2p/
docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..
cd ..
```

**Build time:**
- First build: ~15-20 minutes per container (MATLAB download/install)
- Subsequent builds: ~2-3 minutes (cached layers)

**Verify builds:**
```bash
docker images | grep mur

# Should see:
# mur-landice    latest    ...    2.5 GB
# mur-iquam      latest    ...    2.5 GB
# mur-l2p        latest    ...    2.5 GB
```

### Container Architecture

All containers follow the same multi-stage build pattern:

**Stage 1 (Builder):**
- Base: `mathworks/matlab:r2024b`
- Install MATLAB Compiler
- Compile MATLAB code to standalone executable

**Stage 2 (Runtime):**
- Base: `mathworks/matlab-runtime:r2024b`
- Copy compiled executable from builder
- No MATLAB license required
- Minimal size (~2.5 GB vs ~8 GB full MATLAB)

### Platform Compatibility

**Important:** Build with `--platform linux/amd64` for compatibility:

```bash
# macOS (Apple Silicon) users must specify platform
docker build --platform linux/amd64 -t mur-landice:latest .

# Linux (x86_64) users can omit (but recommended for consistency)
docker build --platform linux/amd64 -t mur-landice:latest .
```

### Registry Deployment (Optional)

**Push to GitHub Container Registry:**

```bash
# Login to GHCR
echo $GITHUB_TOKEN | docker login ghcr.io -u $GITHUB_USERNAME --password-stdin

# Tag containers
docker tag mur-landice:latest ghcr.io/nasa-jpl/mur-landice:latest
docker tag mur-iquam:latest ghcr.io/nasa-jpl/mur-iquam:latest
docker tag mur-l2p:latest ghcr.io/nasa-jpl/mur-l2p:latest

# Push to registry
docker push ghcr.io/nasa-jpl/mur-landice:latest
docker push ghcr.io/nasa-jpl/mur-iquam:latest
docker push ghcr.io/nasa-jpl/mur-l2p:latest
```

**Pull from registry (on other machines):**
```bash
docker pull ghcr.io/nasa-jpl/mur-landice:latest
docker pull ghcr.io/nasa-jpl/mur-iquam:latest
docker pull ghcr.io/nasa-jpl/mur-l2p:latest
```

## Configuration

### Configuration File (config.json)

**Location:** `mur/config.json`

**Example configuration:**

```json
{
  "region": "G10",
  "resolution": "p01",
  "base_dir": "/nas2",
  "work_dir": "/tmp/mur_work",
  "containers": {
    "landice": "mur-landice:latest",
    "iquam": "mur-iquam:latest",
    "l2p": "mur-l2p:latest"
  },
  "l2p_sensors": {
    "AMSR2R": {
      "collection": "AMSR2-REMSS-L2P-v8.2",
      "stability_latency": 2,
      "dayrange": 2
    },
    "MODISA": {
      "collection": "MODIS_A-JPL-L2P-v2019.0",
      "stability_latency": 2,
      "dayrange": 2
    },
    "MODIST": {
      "collection": "MODIS_T-JPL-L2P-v2019.0",
      "stability_latency": 3,
      "dayrange": 2
    },
    "AVMTBG": {
      "collection": "AVHRRMTB_G-NAVO-L2P-v2.0",
      "stability_latency": 2,
      "dayrange": 2
    }
  },
  "iquam": {
    "stability_latency": 2,
    "dayrange": 3
  },
  "paths": {
    "source_data": "/nas2/source",
    "ice_data": "/nas2/source/osi-saf/ice",
    "iquam_data": "/nas2/source/iquam",
    "l2p_data": "/nas2/source/podaac",
    "gds_output": "/nas2/gds",
    "bip_output": "/nas2/bip",
    "bii_output": "/nas2/bii",
    "bic_output": "/nas2/bic",
    "coef_output": "/nas2/coef"
  }
}
```

### Configuration Parameters

**Global Settings:**

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `region` | string | Processing region code | "G10" (Global 1km) |
| `resolution` | string | Grid resolution | "p01" (0.01°) or "p011" (0.011°) |
| `base_dir` | string | Base directory for all data | "/nas2" |
| `work_dir` | string | Temporary working directory | "/tmp/mur_work" |

**Container Images:**

| Parameter | Description |
|-----------|-------------|
| `containers.landice` | Land/ice container tag |
| `containers.iquam` | iQUAM container tag |
| `containers.l2p` | L2P container tag |

**L2P Sensor Configuration:**

Each sensor entry contains:
- `collection`: PO.DAAC collection ID for downloads
- `stability_latency`: Days before data is stable (2-3)
- `dayrange`: Temporal window half-width (typically 2)

**Purge Configuration:**

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `purge.threshold_days` | int | Days after which DOY directories are deleted | 30 |
| `purge.logs_dir` | string | Directory for purge log reports | "testing/preprocessing/logs/purge" |

The purge stage uses `l2p.input_dir` as the download root and `l2p.active_sensors` for the sensor list. It only runs when explicitly requested via `--execute purge`.

**Paths:**

All paths should be absolute. Adjust based on your storage layout:
- `source_data`: Raw input data root
- `*_output`: Preprocessed data output directories

### Environment Variables

**Optional overrides:**

```bash
# Override config file location
export MUR_CONFIG=/path/to/custom_config.json

# Override netrc location
export NETRC_PATH=/path/to/.netrc

# Docker registry prefix
export MUR_REGISTRY=ghcr.io/nasa-jpl

# Logging level
export MUR_LOG_LEVEL=DEBUG
```

### Directory Structure

**Recommended layout:**

```
/nas2/                      # Base directory
├── source/                 # Raw input data
│   ├── osi-saf/ice/       # Ice concentration
│   │   └── YYYY/
│   ├── iquam/             # Buoy data
│   │   └── YYYY/
│   └── podaac/            # L2P satellite data
│       ├── AMSR2R/YYYY/DOY/
│       ├── MODISA/YYYY/DOY/
│       ├── MODIST/YYYY/DOY/
│       └── AVMTBG/YYYY/DOY/
├── gds/                   # Land/ice masks
│   └── YYYY/
├── bip/                   # Ice SST points
│   └── YYYY/
├── bii/                   # Buoy preprocessed
│   └── YYYY/
├── bic/                   # L2P preprocessed
│   ├── AMSR2R/YYYY/
│   ├── MODISA/YYYY/
│   ├── MODIST/YYYY/
│   └── AVMTBG/YYYY/
└── coef/                  # MRVA coefficients [PENDING]
    └── YYYY/
```

**Create directories:**
```bash
BASE=/nas2  # Adjust as needed

mkdir -p $BASE/source/{osi-saf/ice,iquam,podaac/{AMSR2R,MODISA,MODIST,AVMTBG}}
mkdir -p $BASE/{gds,bip,bii,coef}
mkdir -p $BASE/bic/{AMSR2R,MODISA,MODIST,AVMTBG}
```

## Running the Pipeline

### Basic Usage

**Run for yesterday (NRT mode):**
```bash
uv run mur-pipeline --config config.json
```

**Run for specific date:**
```bash
uv run mur-pipeline --config config.json --date 2025-02-11
```

**Run full 9-day window (NRT + REA modes):**
```bash
uv run mur-pipeline --config config.json --all-stages
```

### Command-Line Options

```
usage: mur-pipeline [-h] --config CONFIG [--date DATE] [--all-stages]
                    [--execute STAGE] [--run-mrva] [--netrc-path PATH]
                    [--verbose]

MUR SST Processing Pipeline Orchestrator

required arguments:
  --config CONFIG       Path to config.json file

optional arguments:
  --date DATE           Process specific date (YYYY-MM-DD)
  --all-stages          Process full 9-day window (NRT + REA modes)
  --execute STAGE       Execute specific stage(s): landice, iquam, l2p, purge
  --run-mrva            Run MRVA analysis stage [NOT YET IMPLEMENTED]
  --netrc-path PATH     Path to .netrc file (default: ~/.netrc)
  --verbose, -v         Enable verbose logging
```

### Processing Modes

**NRT (Near Real-Time) Mode:**
```bash
# Process yesterday's data (default)
uv run mur-pipeline --config config.json

# Characteristics:
# - Uses previous day's MUR as background (L=6 coefficients)
# - Skips reprocessing stable data (age >= stability_latency)
# - Fast execution (~1-2 hours)
# - Optimized for operational delivery
```

**REA (Reanalysis) Mode:**
```bash
# Process specific historical date
uv run mur-pipeline --config config.json --date 2024-08-08

# Characteristics:
# - Starts from coarse scale (L=2), no background
# - Respects stability latency, reprocesses if needed
# - Slower execution (~2-4 hours)
# - Optimized for accuracy
```

**Full Window (9-day scan):**
```bash
# Process last 9 days (mix of REA and NRT)
uv run mur-pipeline --config config.json --all-stages

# Processes:
# - Days 1-4: REA mode (historical)
# - Days 5-9: NRT mode (recent)
# - Most comprehensive processing
```

### Execution Examples

**Example 1: Daily NRT Processing**
```bash
#!/bin/bash
# daily_mur.sh - Run at 12:00 UTC daily

cd /path/to/mur
uv run mur-pipeline --config config.json 2>&1 | tee logs/mur_$(date +%Y%m%d).log

# Check for errors
if [ $? -eq 0 ]; then
    echo "MUR processing completed successfully"
else
    echo "MUR processing failed" | mail -s "MUR Alert" admin@example.com
fi
```

**Example 2: Reprocess Specific Date**
```bash
# Reprocess a specific date (e.g., after data correction)
uv run mur-pipeline --config config.json --date 2025-01-15
```

**Example 3: Process Only Specific Components**
```bash
# Process only land/ice
uv run mur-pipeline --config config.json --execute landice

# Process only iQUAM
uv run mur-pipeline --config config.json --execute iquam

# Process multiple stages
uv run mur-pipeline --config config.json --execute landice --execute iquam
```

**Example 4: Purge Old L2P Downloads**
```bash
# Clean up L2P download directories older than the configured threshold
uv run mur-pipeline --config config.json --execute purge
```

The purge stage removes day-of-year directories from the L2P download area that are older than a rolling window threshold (default: 30 days). It reads paths and sensor lists from the pipeline config and writes a dated log report. This stage only runs when explicitly requested via `--execute purge` -- it is not part of the default pipeline run.

## Component-Specific Execution

### Land/Ice Processing

**Direct container execution:**
```bash
docker run --rm \
  --platform linux/amd64 \
  --shm-size=512M \
  -v /nas2/source/osi-saf:/input:ro \
  -v /nas2/gds:/output_gds \
  -v /nas2/bip:/output_bip \
  mur-landice:latest \
  2025 042 G10 p01

# Arguments:
#   2025  - Year
#   042   - Day of year
#   G10   - Region
#   p01   - Resolution (p01=0.01°, p011=0.011°)
```

**Output:**
```
/nas2/gds/2025/G10_2025_042.gds  - Land/ice mask
/nas2/bip/2025/G10_2025_042.bip  - Ice SST points
```

**Runtime:** 2-5 minutes

### iQUAM Buoy Processing

**Direct container execution:**
```bash
docker run --rm \
  --platform linux/amd64 \
  --shm-size=512M \
  -v /nas2/source/iquam:/input:ro \
  -v /nas2/bii:/output \
  -v /tmp/makebic:/cache \
  mur-iquam:latest \
  2025 042 G10 3 nrt

# Arguments:
#   2025  - Year
#   042   - Day of year
#   G10   - Region
#   3     - Day range (±3 days)
#   nrt   - Mode (nrt or rea)
```

**Output:**
```
/nas2/bii/2025/G10_IQUAM0_2025_042.bii
```

**Runtime:** 5-15 minutes (first run), <1 minute (cached)

### L2P Satellite Processing

**Process single sensor/day:**
```bash
docker run --rm \
  --platform linux/amd64 \
  --shm-size=512M \
  -v /nas2/source/podaac/MODISA:/input:ro \
  -v /nas2/bic/MODISA:/output \
  mur-l2p:latest \
  MODISA Global /input /output 2025 042 1

# Arguments:
#   MODISA  - Sensor name
#   Global  - Region
#   /input  - Input directory (L2P granules)
#   /output - Output directory (BIC files)
#   2025    - Year
#   042     - Day of year
#   1       - Rewrite flag (0=skip existing, 1=overwrite)
```

**Output:**
```
/nas2/bic/MODISA/2025/G10_MODISA_2025_042.bic.gz
/nas2/bic/MODISA/2025/L2Plist_G10_MODISA_2025_042.txt
```

**Runtime:**
- AMSR2R: 5-10 minutes
- MODISA: 10-20 minutes
- MODIST: 10-20 minutes
- AVMTBG: 5-10 minutes

**Process all sensors in parallel:**
```bash
# Run all sensors concurrently
for sensor in AMSR2R MODISA MODIST AVMTBG; do
    docker run --rm --shm-size=512M \
        -v /nas2/source/podaac/$sensor:/input:ro \
        -v /nas2/bic/$sensor:/output \
        mur-l2p:latest \
        $sensor Global /input /output 2025 042 1 &
done
wait

echo "All L2P sensors completed"
```

## Monitoring and Logging

### Log Locations

**Pipeline orchestrator logs:**
```bash
# Default: stdout/stderr
uv run mur-pipeline --config config.json 2>&1 | tee logs/pipeline.log

# Logs include:
# - Stage execution status
# - Container execution commands
# - Success/failure counts
# - Timing statistics
```

**Container logs:**
```bash
# View recent container logs
docker logs <container_id>

# Follow logs in real-time
docker logs -f <container_id>

# Save logs to file
docker logs <container_id> > landice.log 2>&1
```

**Component-specific logs:**
```
/nas2/logs/landice/YYYY/DOY.log
/nas2/logs/iquam/YYYY/DOY.log
/nas2/logs/l2p/SENSOR/YYYY/DOY.log
```

### Monitoring Tools

**Check processing status:**
```bash
# View running containers
docker ps

# Monitor resource usage
docker stats

# System resources
htop  # or top
df -h  # Disk usage
```

**Check output files:**
```bash
# Count files for today
find /nas2/bic -name "*_2025_042.bic.gz" | wc -l

# Check file sizes
ls -lh /nas2/bic/*/2025/*_2025_042.bic.gz

# Verify all sensors processed
for sensor in AMSR2R MODISA MODIST AVMTBG; do
    if [ -f /nas2/bic/$sensor/2025/G10_${sensor}_2025_042.bic.gz ]; then
        echo "$sensor: OK"
    else
        echo "$sensor: MISSING"
    fi
done
```

### Performance Metrics

**Track processing times:**
```bash
# Add timing to pipeline execution
time uv run mur-pipeline --config config.json

# Typical durations:
# - Land/Ice: 2-5 minutes
# - iQUAM: 5-15 minutes (first run), <1 min (cached)
# - L2P (all sensors): 30-60 minutes (sequential), 15-25 min (parallel)
# - Total preprocessing: 40-80 minutes
```

**Storage usage tracking:**
```bash
# Check daily growth
du -sh /nas2/bic/*/2025/ | sort -h

# Total storage by component
du -sh /nas2/{source,gds,bip,bii,bic}
```

## Production Deployment

### Cron Scheduling

**Daily NRT processing (12:00 UTC):**
```cron
# /etc/cron.d/mur-processing

0 12 * * * mur_user cd /path/to/mur && uv run mur-pipeline --config config.json >> /var/log/mur/daily.log 2>&1
```

**Hourly L2P downloads:**
```cron
# Download MODISA data every hour
0 * * * * mur_user /path/to/scripts/download_modisa.sh >> /var/log/mur/downloads.log 2>&1

# Download MODIST data every hour
15 * * * * mur_user /path/to/scripts/download_modist.sh >> /var/log/mur/downloads.log 2>&1
```

**Example download script:**
```bash
#!/bin/bash
# download_modisa.sh

TODAY=$(date -u +%Y-%m-%d)

podaac-data-subscriber \
    -c MODIS_A-JPL-L2P-v2019.0 \
    -d /nas2/source/podaac/MODISA \
    --start-date "${TODAY}T00:00:00Z" \
    --end-date "${TODAY}T23:59:59Z" \
    --verbose
```

### Systemd Service (Alternative to Cron)

**Create service file:** `/etc/systemd/system/mur-processing.service`

```ini
[Unit]
Description=MUR SST Processing Pipeline
After=network.target docker.service

[Service]
Type=oneshot
User=mur_user
WorkingDirectory=/path/to/mur
Environment="PATH=/home/mur_user/.cargo/bin:/usr/bin"
ExecStart=/home/mur_user/.cargo/bin/uv run mur-pipeline --config config.json
StandardOutput=append:/var/log/mur/pipeline.log
StandardError=append:/var/log/mur/pipeline.log

[Install]
WantedBy=multi-user.target
```

**Create timer:** `/etc/systemd/system/mur-processing.timer`

```ini
[Unit]
Description=Run MUR processing daily at 12:00 UTC

[Timer]
OnCalendar=*-*-* 12:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable mur-processing.timer
sudo systemctl start mur-processing.timer

# Check status
sudo systemctl status mur-processing.timer
sudo systemctl list-timers mur-processing.timer
```

### High-Availability Setup

**Multiple processing nodes:**
```bash
# Node 1: Process even days
0 12 * * * [ $(($(date +\%d) \% 2)) -eq 0 ] && /path/to/run_pipeline.sh

# Node 2: Process odd days
0 12 * * * [ $(($(date +\%d) \% 2)) -eq 1 ] && /path/to/run_pipeline.sh
```

**Shared storage (NFS/GlusterFS):**
```bash
# Mount shared storage
sudo mount -t nfs storage.example.com:/nas2 /nas2

# Add to /etc/fstab for persistence
storage.example.com:/nas2  /nas2  nfs  defaults  0  0
```

## Troubleshooting

### Common Issues

**Issue 1: Docker permission denied**
```
Error: permission denied while trying to connect to Docker daemon
```

**Solution:**
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Apply changes (logout/login or use newgrp)
newgrp docker

# Verify
docker ps
```

**Issue 2: Container fails with "no space left on device"**
```
Error: no space left on device
```

**Solution:**
```bash
# Check disk usage
df -h

# Clean Docker cache
docker system prune -a --volumes

# Check Docker disk usage
docker system df
```

**Issue 3: MATLAB Runtime error (shm-size)**
```
Error: Insufficient shared memory
```

**Solution:**
```bash
# Add --shm-size flag
docker run --shm-size=512M ...

# Or increase if needed
docker run --shm-size=1G ...
```

**Issue 4: L2P download fails (authentication)**
```
Error: 401 Unauthorized
```

**Solution:**
```bash
# Verify .netrc file
cat ~/.netrc
chmod 600 ~/.netrc

# Test authentication
curl -n https://podaac.jpl.nasa.gov/

# Re-approve PO.DAAC app
# Visit: https://urs.earthdata.nasa.gov/approve_app?client_id=BO_n7nTIlMljdvU6kRRB3g
```

**Issue 5: Missing output files**
```
Expected output not created
```

**Solution:**
```bash
# Check container logs
docker logs <container_id>

# Verify input data exists
ls /nas2/source/podaac/MODISA/2025/042/

# Check permissions
ls -ld /nas2/bic/MODISA/

# Run with verbose logging
docker run -e VERBOSE=1 ...
```

### Debug Mode

**Enable verbose logging:**
```bash
# Pipeline orchestrator
uv run mur-pipeline --config config.json --verbose

# Container debugging
docker run -e DEBUG=1 -e VERBOSE=1 ...
```

**Interactive container debugging:**
```bash
# Override entrypoint to get shell
docker run -it --rm --entrypoint /bin/bash mur-landice:latest

# Inside container, run commands manually
ls /app
./landice_wrapper 2025 042 G10 p01
```

### Performance Troubleshooting

**Slow processing:**
```bash
# Check CPU usage
htop

# Check I/O wait
iostat -x 5

# Check network (if downloading)
iftop

# Run single sensor to isolate issue
docker run ... mur-l2p:latest AMSR2R ...
```

**High memory usage:**
```bash
# Monitor container memory
docker stats

# Limit container memory
docker run --memory=4g --memory-swap=8g ...
```

### Log Analysis

**Search for errors:**
```bash
# Pipeline logs
grep -i error logs/pipeline.log

# Container logs
docker logs <container_id> 2>&1 | grep -i error

# System logs
journalctl -u mur-processing -n 100
```

**Common error patterns:**
```bash
# Missing input files
grep "FileNotFoundError" logs/*.log

# Container crashes
grep "signal" logs/*.log

# Timeout issues
grep "timeout" logs/*.log
```

---

## Summary

The MUR preprocessing pipeline provides:

- **Easy installation:** uv-based Python environment + Docker containers
- **Flexible configuration:** JSON config file with path customization
- **Multiple modes:** NRT for speed, REA for accuracy
- **Component execution:** Run individual stages or full pipeline
- **Production-ready:** Cron/systemd scheduling, logging, monitoring
- **Troubleshooting:** Comprehensive debug options and common solutions

**Current Status:** Preprocessing components (Land/Ice, iQUAM, L2P) are operational. MRVA analysis and NetCDF output generation are in development.

---

## References

- [OVERVIEW.md](OVERVIEW.md) - System architecture overview
- [DATA_LIFECYCLE.md](DATA_LIFECYCLE.md) - Data flow and caching
- [SENSOR_ADAPTATION.md](SENSOR_ADAPTATION.md) - Adding new sensors
- Component READMEs:
  - [landice/README.md](../landice/README.md)
  - [iquam/README.md](../iquam/README.md)
  - [l2p/README.md](../l2p/README.md)

---

*Last Updated: 2025-01-18*
*Documentation Version: 1.0 (Preprocessing Components)*
