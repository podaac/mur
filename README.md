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

## CalTech Copyright
Copyright [2025], by the California Institute of Technology. ALL RIGHTS RESERVED. United States Government Sponsorship acknowledged. Any commercial use must be negotiated with the Office of Technology Transfer at the California Institute of Technology.
 
This software may be subject to U.S. export control laws. By accepting this software, the user agrees to comply with all applicable U.S. export laws and regulations. User has the responsibility to obtain export licenses, or other export authority as may be required before exporting such information to foreign countries or providing access to foreign persons.
