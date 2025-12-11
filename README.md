# mur

The NASA Physical Oceanography Distributed Active Archive Center (PO.DAAC) Multi-scale Ultra-high Resolution (MUR) and MUR Reanalysis and Validation for Applications (MRVA) programs aim to deliver high-resolution sea surface temperature (SST) products to support Earth system science, weather forecasting, climate research, and decision-making across ocean, coastal, and polar domains.

The MUR workflow is made up of several components:

1) Input: Landmask & Ice, IQUAM Buoy (In Situ), Level 2P Satellite Sensors
2) Processing: MRVA
3) Output (Aggregates results and uploads to S3)

## Documentation

**Comprehensive documentation is available in the [`documentation/`](documentation/) directory:**

- **[OVERVIEW.md](documentation/OVERVIEW.md)** - High-level system architecture and component overview
- **[ALGORITHM_FLOW.md](documentation/ALGORITHM_FLOW.md)** - MRVA algorithm details and multi-scale processing
- **[DATA_LIFECYCLE.md](documentation/DATA_LIFECYCLE.md)** - Data flow, caching, and storage management
- **[SENSOR_ADAPTATION.md](documentation/SENSOR_ADAPTATION.md)** - Guide for integrating new satellite sensors
- **[PIPELINE_CONFIGURATION.md](documentation/PIPELINE_CONFIGURATION.md)** - Installation, configuration, and operation
- **[LANDICE_ENCODING.md](documentation/LANDICE_ENCODING.md)** - Land/ice mask encoding reference
- **[FUTURE_ENHANCEMENTS.md](documentation/FUTURE_ENHANCEMENTS.md)** - Planned features and considered enhancements

**Component-specific documentation:**
- [Land/Ice Processing](landice/README.md)
- [L2P Satellite Processing](l2p/README.md)
- [iQUAM Buoy Processing](iquam/README.md)

## Quick Start

### Environment Setup

Install dependencies and create the uv environment:

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync environment (creates .venv and installs all dependencies)
cd mur
uv sync

# Activate the environment (optional - uv handles this automatically)
source .venv/bin/activate

# This setup creates convenient command shortcuts when the venv is active:
#   mur-pipeline  - Pipeline orchestrator (replaces: uv run run_mur_pipeline.py)
#   mur-viewer    - Data file viewer (replaces: uv run dataviewer/dataviewer.py)
#
# You can use these commands directly if the venv is active,
# or prefix with 'uv run' without activating:
#   uv run mur-pipeline --config config.json
```

### Production-Style Pipeline Orchestrator

A production-style test orchestrator is available that mimics the architecture of `nrtMRVA.py`:

```bash
# Build containers (first time only)
cd landice && docker build --platform linux/amd64 -t landice:latest .
cd ../iquam && docker build --platform linux/amd64 -t iquam:latest -f Dockerfile ..
cd ../l2p && docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..
cd ..

# Run for yesterday's data (NRT mode)
mur-pipeline --config config.json
# or: uv run run_mur_pipeline.py --config config.json

# Run full 9-day window (REA + NRT modes)
mur-pipeline --config config.json --all-stages

# Run for specific date
mur-pipeline --config config.json --date 2024-08-08

# Run with MRVA stage (when ready)
mur-pipeline --config config.json --all-stages --run-mrva
```

**Key Features:**
- **Cron-style L2P downloads**: Mimics production hourly download jobs
- **Direct container calls**: L2P containers called directly (not via Python helpers)
- **NRT vs REA modes**: Automatic mode detection based on data age
- **Stability latency**: Smart reprocessing only when data changes
- **MRVA-ready**: Stage 5 prepared but not yet executed

See the [Test Driver Documentation](#test-driver) section below for full details.

## InputGen Operations

This component creates coordinating JSON files that can be used by exectuion infrastructure to execute the MUR algorithms in parallel.

Runtime: 2025-08-13T20:55:10,308 root INFO Execution time: 0:02:29.569614

See this README for details: [InputGen README](inputgen/README.md)

## Land Ice Operations

This component prepares landmask and sea ice boundary data used in downstream MUR processing. It generates and runs MATLAB scripts that apply land and ice masking operations to MUR SST inputs for the previous 9 days. Two grid resolutions (`p01` at 0.01° and `p011` at 0.011°) are supported. It is parallelized on the day which are arguments to the script. The InputGen operations produce the required date ranges to execute on.

See this README for details: [Land Ice README](landice/README.md)

## L2P Sensor Operations

This component downloads (or loads) L2P Sensor data from Earthdata and combines the data in to a binary file to be read by the MRVA process. It is parallelized on the sensor and day which are arguments to the script. The InputGen operations produce the required sensor and date ranges to execute on.

Runtime: 2025-08-13T20:27:57,501 root INFO Execution time: 0:32:30.754806 (fully parallelized )

See this README for details: [L2P README](l2p/README.md)

---

## Data Viewer

The `mur-viewer` tool allows you to inspect and visualize MUR processing data files.

### Supported Formats

- **`.bip`**: Ice SST point data
- **`.gds`**: Gridded land/ice mask
- **`.bii`**: In-situ buoy observations (iQUAM)
- **`.bic`**: Satellite L2P swath data
- **`.biq`**: Unified observation format
- **`.bin`**: Legacy satellite format
- **`.cXX`**: Multi-scale coefficient files (`.c02` through `.c11`)
- **`.uXX`**: Uncertainty coefficient files
- **`.nc`/`.nc4`**: NetCDF output files

### Usage

```bash
# View file information
mur-viewer testing/preprocessing/output/landice/2024/Global_ice_2024_220.bip

# View and plot data
mur-viewer testing/preprocessing/output/iquam/2024/Global_IQUAM0_2024_220.bii --plot

# Compare two files
mur-viewer file1.bip file2.bip --compare

# Export to text file
mur-viewer data.biq --export output.txt

# View large grid with resampling
mur-viewer landice_2024_220.gds --plot --resample 4
```

### Example Output

```
================================================================================
File: Global_IQUAM0_2024_220.bii
Format: BII
Path: testing/preprocessing/output/iquam/2024/Global_IQUAM0_2024_220.bii
================================================================================

Year: 2024
Day of year: 220
Number of observations: 12,543

Longitude range: [-179.9800, 179.9850]
Latitude range:  [-77.8900, 82.4500]
SST range:       [-1.8000, 32.5000] °C
SST mean:        18.2340 °C
SST std:         8.4521 °C

Platform types: [1.0 2.0 3.0 4.0]
  1: 8,234 observations (65.66%)
  2: 2,145 observations (17.11%)
  3: 1,876 observations (14.96%)
  4: 288 observations (2.30%)
```

When using `--plot`, matplotlib will display:
- Geographic distribution
- SST histograms
- Weight/bias/error distributions
- Ice concentration maps (for `.gds` files)

---

## Test Driver (Pipeline Orchestrator)

The `run_mur_pipeline.py` script is a **production-style orchestrator** that mimics the architecture and decision logic of `nrtMRVA.py` (the production orchestration system). It demonstrates how an orchestration system should manage the complete MUR processing pipeline using containers.

### Architecture Philosophy

**Production System (`mur-internal/cyc4/nrtMRVA.py`):**
- Generates MATLAB scripts on-the-fly and executes them directly
- L2P data downloaded via separate hourly cron jobs
- Processing runs in batch mode analyzing 9-day windows
- Distinguishes between NRT (near real-time/interim) and REA (reanalysis/final) modes

**Test Orchestrator (`run_mur_pipeline.py`):**
- Uses containers instead of MATLAB scripts
- Downloads L2P data separately (mimicking cron behavior)
- Calls L2P containers directly (not through Python helper scripts)
- Maintains same NRT/REA logic and stability latency decisions
- Prepares MRVA stage but doesn't execute it yet

### Features

- **Production-accurate orchestration**: Follows nrtMRVA.py control flow
- **Cron-style downloads**: L2P downloads separated from processing
- **Direct container execution**: No Python wrapper scripts for processing
- **NRT/REA mode detection**: Automatic processing mode based on data age
- **Stability latency**: Smart reprocessing only when source data changes
- **Multi-sensor processing**: Handles temporal windows for each sensor
- **MRVA-ready**: Stage 5 structure prepared for future containerization
- **Statistics tracking**: Detailed success/fail/skip counts per stage

### Prerequisites

1. **uv** (Python package manager):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Docker containers** (build from respective directories):
   ```bash
   cd landice && docker build --platform linux/amd64 -t landice:latest .
   cd ../iquam && docker build --platform linux/amd64 -t iquam:latest -f Dockerfile ..
   cd ../l2p && docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..
   ```

3. **Testing directory structure**: Already set up in `mur/testing/`

4. **Input data files**: Copy base masks and MATLAB index files to `testing/preprocessing/inputs/`

### Configuration

Edit `config.json` to customize processing:

```json
{
  "landice": {
    "container_image": "landice:latest",
    "input_dir": "testing/preprocessing/inputs",
    "output_dir": "testing/preprocessing/output/landice"
  },
  "l2p": {
    "container_image": "mur-l2p:latest",
    "input_dir": "testing/preprocessing/inputs/l2p",
    "output_dir": "testing/preprocessing/output/l2p",
    "active_sensors": ["AMSR2R", "MODISA", "MODIST", "AVMTBG"],
    "sensors": {
      "AMSR2R": {
        "collection_name": ["AMSR2-REMSS-L2P-v8.2"],
        "region": "Global",
        "La": 2,
        "Lb": 8,
        "stable": 2
      }
      // ... more sensors
    }
  },
  "iquam": {
    "container_image": "iquam:latest",
    "output_dir": "testing/preprocessing/output/iquam",
    "cache_dir": "testing/preprocessing/cache/iquam",
    "logs_dir": "testing/preprocessing/logs"
  }
}
```

See [config.example.json](config.example.json) for complete documentation.

### Usage Examples

**Process yesterday only** (NRT mode, default):
```bash
mur-pipeline --config config.json
```

**Process full 9-day window** (REA + NRT modes, mimics nrtMRVA.py):
```bash
mur-pipeline --config config.json --all-stages
```

**Process specific date**:
```bash
mur-pipeline --config config.json --date 2024-08-08
```

**Include MRVA stage** (prepared but not executed):
```bash
mur-pipeline --config config.json --all-stages --run-mrva
```

**Enable debug logging**:
```bash
mur-pipeline --config config.json --debug
```

> **Note**: You can also use `uv run run_mur_pipeline.py` instead of `mur-pipeline` if you prefer the direct script invocation.

### Processing Stages

The orchestrator runs these stages in order:

**Stage 1: Land/Ice Mask Generation**
- Downloads OSI-SAF ice concentration data
- Generates `.gds` mask files and `.bip` ice SST files
- Runs at two resolutions (0.01° and 0.25°)

**Stage 2: L2P Data Download** (Cron-Style)
- Downloads L2P satellite data via earthaccess (S3 in-region)
- Mimics production hourly cron job pattern
- Handles ±dayrange temporal window per sensor
- Respects stability latency (won't redownload stable data)

**Stage 3: L2P Container Processing** (Direct Call)
- Processes downloaded L2P files → BIC format
- Called directly (5-arg container interface)
- No Python helper scripts (mimics nrtMRVA.py pattern)
- Generates bias/error coefficient files

**Stage 4: iQUAM Buoy Processing**
- Downloads NOAA iQUAM monthly files (cached)
- Extracts daily subset with ±3 day window
- Applies quality filtering (quality_level >= 5)
- Generates `.bii` binary integer format

**Stage 5: MRVA Analysis** (Prepared, Not Executed)
- Structure ready for future MRVA container
- Mode detection (NRT interim vs REA final)
- Will process BIC/BII/BIP inputs → MUR product
- Use `--run-mrva` flag when containerized

### Output Structure

Outputs are organized in `testing/preprocessing/output/`:

```
testing/preprocessing/output/
├── landice/
│   └── {YEAR}/
│       ├── landice_{YYYY}_{DOY}.gds.gz          # 0.01° land/ice mask
│       ├── landiceP01_{YYYY}_{DOY}.gds.gz       # 0.25° land/ice mask
│       ├── Global_ice_{YYYY}_{DOY}.bip.gz       # 0.01° ice SST
│       └── Global_iceP01_{YYYY}_{DOY}.bip.gz    # 0.25° ice SST
├── l2p/
│   └── {SENSOR}/
│       ├── Global_{SENSOR}_{YYYY}_{DOY}.bic.gz  # BIC satellite data
│       └── L2Plist_Global_{SENSOR}_{YYYY}_{DOY}.txt
└── iquam/
    └── {YEAR}/
        └── Global_IQUAM0_{YYYY}_{DOY}.bii       # BII buoy data
```

### Processing Timeline

**Single Day** (yesterday, NRT mode):
- Stage 1 (Land/Ice): ~5 minutes
- Stage 2 (L2P Download): ~20-40 minutes per sensor, 4 sensors
- Stage 3 (L2P Processing): ~5-10 minutes per sensor
- Stage 4 (iQUAM): ~10 minutes
- **Total**: ~60-90 minutes

**Full 9-Day Window** (--all-stages):
- Processes days: today-9 to today-1
- REA mode (days 9-4): Final run, stable data
- NRT mode (days 3-1): Interim run, may reprocess
- **Total**: ~8-12 hours depending on data availability

### NRT vs REA Modes

The orchestrator automatically detects processing mode based on data age:

**REA (Reanalysis) Mode** - Days 9-4 behind current:
- "Final run" - data is stable
- Won't reprocess existing outputs
- No redownloading of source data
- Generates authoritative products

**NRT (Near Real-Time) Mode** - Days 3-1 behind current:
- "Interim run" - data may still update
- Will reprocess if source data changed
- Checks stability latency per sensor/buoy
- May produce multiple versions as data improves

### Troubleshooting

**Container not found**:
```bash
# Rebuild the missing container
cd {module} && docker build --platform linux/amd64 -t {module}:latest .
```

**Input files missing**:
```bash
# Check inputs directory
ls -R testing/preprocessing/inputs/

# Copy required files (see Prerequisites section)
```

**Memory issues**:
```bash
# Increase Docker memory limit (Docker Desktop > Settings > Resources)
# Or edit memory flags in run_mur_pipeline.py
```

**Check logs**:
```bash
# iQUAM logs
cat testing/preprocessing/logs/*.log

# Docker logs
docker logs {container_id}
```

### Next Steps

**Phase 1 (Current):** Pre-processing stages containerized and orchestrated
- ✓ Land/Ice masks
- ✓ L2P satellite data (download + processing)
- ✓ iQUAM buoy data
- ○ MRVA (structure prepared, not executed)

**Phase 2 (Future):** MRVA containerization
- Containerize cyc4/nrtMRVA.py MRVA stage
- Integrate with orchestrator using `--run-mrva` flag
- Generate coefficient files (.c02 through .c11)
- Produce final MUR NetCDF4 product

**Phase 3 (Future):** Full production deployment
- Kubernetes-based orchestration
- Automated scheduling (replacing cron jobs)
- Cloud-native storage integration
- Monitoring and alerting

### File Formats

- **`.bip`**: Binary Input Point - ice SST point data
- **`.gds`**: Gridded Data Set - land/ice mask grids
- **`.bic`**: Binary Input Coefficient - satellite swath with bias/error
- **`.bii`**: Binary Input Integer - in-situ observations (scaled int16)

See [PROCESSING_FLOW_REPORT.md](../mur-internal/PROCESSING_FLOW_REPORT.md) for complete format specifications.
