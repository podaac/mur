# MUR Pipeline Configuration and Operation

## Introduction

This document describes how to install, configure, and run the MUR preprocessing pipeline. It covers environment setup, container builds, configuration files, command-line operation, and troubleshooting.

**Note:** All four stages (Land/Ice, iQUAM, L2P, MRVA) are implemented and operational via `run_mur_pipeline.py` (the `mur-pipeline` command). Every container now takes its inputs as explicit named flags rather than bind-mounted directories — see [STATIC_DATA.md](STATIC_DATA.md) and each container's README for the full flag list.

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
git clone https://github.com/podaac/mur.git
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

**Prerequisite:** the build needs a MATLAB license server. Copy the template and edit it before the first build:

```bash
cd mur/
cp network.lic.example network.lic
# Edit network.lic with your license server details
```

**Build with `build_module.sh` (from the `mur/` directory):**

```bash
# Build everything: iquam, l2p, landice, mrva
./build_module.sh all

# Or one module at a time
./build_module.sh landice
./build_module.sh iquam
./build_module.sh l2p
./build_module.sh mrva

# Debug build: symbols, bounds checking, FP-exception trapping (still tagged :latest)
./build_module.sh mrva --debug

# Force a rebuild that ignores the Docker layer cache
./build_module.sh all --no-cache
```

The script handles everything the raw `docker build` commands used to require by hand:

- Builds `mur-matlab-base:r2024b` first (via `build_matlab_base.sh`) if it isn't present
- Fails early with a clear message if `network.lic` is missing
- Always passes `--platform linux/amd64`
- Uses the parent `mur/` directory as build context so `common/` is reachable
- Tags images `mur-iquam:latest`, `mur-l2p:latest`, `mur-landice:latest`, `mur-mrva:latest` — the names the `container_image` fields in `config.json` expect

**Build time:**
- Base image (first time only): ~15-20 minutes (MATLAB runtime download/install)
- Per module, first build: ~10-20 minutes (MATLAB compilation; MRVA also compiles Fortran)
- Subsequent builds: ~2-3 minutes (cached layers)

**Verify builds:**
```bash
docker images | grep mur

# Should see:
# mur-matlab-base  r2024b    ...    3.5 GB
# mur-landice      latest    ...    2.5 GB
# mur-iquam        latest    ...    2.5 GB
# mur-l2p          latest    ...    2.5 GB
# mur-mrva         latest    ...    2.5 GB
```

### Manual Builds (Advanced)

`build_module.sh` is the supported path — use raw `docker build` only when you need something the script doesn't cover: building the base image separately, pinning a non-`latest` tag, bisecting a Dockerfile change, or wiring the build into external CI.

Two rules apply to every module:

1. **Build context is the parent `mur/` directory** (the trailing `..`), because each Dockerfile pulls shared code from `common/`. The module's own `.dockerignore` controls what gets in.
2. **Always pass `--platform linux/amd64`**, including on Apple Silicon — production runs x86_64.

**Step 1 — base image** (all modules build `FROM mur-matlab-base:r2024b`):

```bash
cd mur/matlab-base
docker build --platform linux/amd64 -t mur-matlab-base:r2024b -f Dockerfile ..
```

**Step 2 — modules** (any order; each only needs the base image):

```bash
cd mur/landice
docker build --platform linux/amd64 -t mur-landice:latest -f Dockerfile ..

cd mur/iquam
docker build --platform linux/amd64 -t mur-iquam:latest -f Dockerfile ..

cd mur/l2p
docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..

cd mur/mrva
docker build --platform linux/amd64 -t mur-mrva:latest -f Dockerfile ..
```

**Debug build** — what `build_module.sh --debug` passes:

```bash
docker build --platform linux/amd64 --build-arg DEBUG=1 -t mur-mrva:latest -f Dockerfile ..
```

If you tag an image anything other than `mur-<module>:latest`, update the matching `container_image` field in your `config.json`, or the pipeline will not find it.

### Container Architecture

All containers follow the same multi-stage build pattern:

**Stage 1 (Builder):**
- Base: `mur-matlab-base:r2024b` (itself built `FROM mathworks/matlab:r2024b` with the compiler and runtime installer baked in, so modules don't each re-download it)
- Compile MATLAB code to a standalone executable
- MRVA adds an earlier Fortran stage (`intel/oneapi-hpckit`) for its compiled solvers

**Stage 2 (Runtime):**
- Base: MATLAB Runtime R2024b
- Copy compiled executable from builder
- No MATLAB license required
- Minimal size (~2.5 GB vs ~8 GB full MATLAB)

### Platform Compatibility

All images target `linux/amd64`, matching production. `build_module.sh` passes `--platform linux/amd64` for you; only manual `docker build` invocations need the flag spelled out, and they need it on Apple Silicon and on x86_64 Linux alike for consistent results.

### Registry Deployment (Optional)

**Push to GitHub Container Registry:**

```bash
# Login to GHCR
echo $GITHUB_TOKEN | docker login ghcr.io -u $GITHUB_USERNAME --password-stdin

# Tag containers
docker tag mur-landice:latest ghcr.io/podaac/mur-landice:latest
docker tag mur-iquam:latest ghcr.io/podaac/mur-iquam:latest
docker tag mur-l2p:latest ghcr.io/podaac/mur-l2p:latest

# Push to registry
docker push ghcr.io/podaac/mur-landice:latest
docker push ghcr.io/podaac/mur-iquam:latest
docker push ghcr.io/podaac/mur-l2p:latest
```

**Pull from registry (on other machines):**
```bash
docker pull ghcr.io/podaac/mur-landice:latest
docker pull ghcr.io/podaac/mur-iquam:latest
docker pull ghcr.io/podaac/mur-l2p:latest
```

## Configuration

### Configuration File (config.json)

**Location:** `mur/config.json` for local testing (relative `testing/...` paths); `config.container.json` (or any path you point `--config` at) for a real deployment with absolute paths. See `config.example.json` for a fully-commented starting point.

**This is the actual schema `run_mur_pipeline.py` reads today** — one top-level object per stage (`landice`, `l2p`, `iquam`, `mrva`), no `containers`/`paths`/`l2p_sensors` wrapper objects:

```json
{
  "landice": {
    "container_image": "mur-landice:latest",
    "static_resources_dir": "testing/static-resources",
    "output_dir_p011": "testing/preprocessing/output/landice-p011",
    "output_dir_p01": "testing/preprocessing/output/landice-p01"
  },
  "l2p": {
    "container_image": "mur-l2p:latest",
    "input_dir": "testing/preprocessing/inputs/l2p",
    "output_dir": "testing/preprocessing/output/l2p",
    "active_sensors": ["AMSR2R", "MODISA", "MODIST", "AVMTAG", "AVMTBG"],
    "sensors": {
      "AMSR2R": {
        "collection_name": ["AMSR2-REMSS-L2P-v8.2", "AMSR2-REMSS-L2P_RT-v8.2"],
        "start_date": "2023-01-01T00:00:00Z",
        "region": "Global",
        "day_range": [2, 2],
        "stable": 2
      }
    }
  },
  "iquam": {
    "container_image": "mur-iquam:latest",
    "output_dir": "testing/preprocessing/output/iquam",
    "logs_dir": "testing/preprocessing/logs",
    "buoy_dayrange": 3,
    "stable_latency": 2
  },
  "mrva": {
    "container_image": "mur-mrva:latest",
    "input_dir_bic": "testing/preprocessing/output/l2p",
    "input_dir_iquam": "testing/preprocessing/output/iquam",
    "input_dir_landice_p011": "testing/preprocessing/output/landice-p011",
    "input_dir_landice_p01": "testing/preprocessing/output/landice-p01",
    "static_resources_dir": "testing/static-resources",
    "output_dir_csp": "testing/mrva/output/csp",
    "output_dir_netcdf": "testing/mrva/output/netcdf",
    "cache_dir": "testing/mrva/cache",
    "logs_dir": "testing/mrva/logs",
    "active_sensors": ["IQUAM0", "AMSR2R", "MODISA", "MODIST", "AVMTAG", "AVMTBG"],
    "sensors": {
      "IQUAM0": {"directory": "iquam", "region": "Global", "day_range": 3},
      "AMSR2R": {"directory": "AMSR2R", "region": "Global", "day_range": 2}
    }
  }
}
```

See `config.example.json` for every sensor filled in and inline comments. `l2p.sensors[X].day_range` is a `[backward, forward]` pair; `mrva.sensors[X].day_range` is a single symmetric int — these are genuinely different shapes between the two stages, not a typo.

### Configuration Parameters

**Per-stage `container_image`:** the Docker tag `run_mur_pipeline.py` invokes for that stage (default: `mur-<stage>:latest`).

**`landice`:**

| Parameter | Description |
|-----------|-------------|
| `static_resources_dir` | Root containing `grids/`, `mat/p01/`, `mat/p011/` — resolved into landice's six explicit `--*-file` flags (see [STATIC_DATA.md](STATIC_DATA.md)) |
| `output_dir_p011` / `output_dir_p01` | Per-resolution output roots |

**`l2p`:**

| Parameter | Description |
|-----------|-------------|
| `input_dir` | Root of downloaded L2P granules (`<input_dir>/<SENSOR>/<year>/<doy>/`), populated separately by the `l2p-download` stage or a download cron — never by `l2p` itself |
| `output_dir` | BIC output root |
| `active_sensors` | Sensors processed by default (overridable per-run with `--sensors`) |
| `sensors.<NAME>.collection_name` | PO.DAAC collection ID(s) for downloads — a list, since AMSR2R has two (final + RT) |
| `sensors.<NAME>.day_range` | `[backward, forward]` days around the analysis day |
| `sensors.<NAME>.stable` | Days before data is considered stable (stops being rewritten) |

**`iquam`:** `output_dir`, `logs_dir`, `buoy_dayrange` (± window), `stable_latency`.

**`mrva`:** `input_dir_bic`/`input_dir_iquam`/`input_dir_landice_p011`/`input_dir_landice_p01` (read from the other stages' `output_dir`s — keep these in sync, `run_mur_pipeline.py` validates it), `static_resources_dir`, `output_dir_csp`/`output_dir_netcdf`, `cache_dir`, `logs_dir`, `active_sensors` (now includes `IQUAM0` alongside the satellite sensors — MRVA's BIC+iQuam fan-in is built as one unified manifest), `sensors.<NAME>.day_range` (flat int, not a pair).

**Purge Configuration:**

The purge stage uses `l2p.input_dir` as the download root and `l2p.active_sensors` for the sensor list; its threshold/log-dir behavior is controlled by CLI flags (`--deep-purge`), not config keys. It only runs when explicitly requested via `--execute purge`.

### Environment Variables

**Optional overrides:**

```bash
# Override config file location
export MUR_CONFIG=/path/to/custom_config.json

# Override netrc location
export NETRC_PATH=/path/to/.netrc

# Docker registry prefix
export MUR_REGISTRY=ghcr.io/podaac

# Logging level
export MUR_LOG_LEVEL=DEBUG
```

### Directory Structure

**Actual layout**, matching `config.json`'s defaults (relative to the repo root; use absolute paths in a real deployment config, as `config.container.json` does):

```
testing/
├── static-resources/                    # landice.static_resources_dir, mrva.static_resources_dir
│   ├── grids/, mat/p01/, mat/p011/       # landice's six static files
│   ├── seasonal/mur_###.nc               # mrva --seasonal-file
│   ├── landice/CylinderP01_edge.bip      # mrva --polar-cap-edge-file
│   └── L4/                               # mrva --l4-reference-root (optional bootstrap)
├── preprocessing/
│   ├── inputs/l2p/<SENSOR>/YYYY/DOY/     # l2p.input_dir -- populated by the l2p-download
│   │                                     #   stage or a download cron, never by `l2p` itself
│   └── output/
│       ├── landice-p01/YYYY/, landice-p011/YYYY/   # landice output_dir_p01/p011
│       ├── l2p/<SENSOR>/YYYY/            # l2p.output_dir == mrva.input_dir_bic
│       └── iquam/YYYY/                   # iquam.output_dir == mrva.input_dir_iquam
└── mrva/
    ├── output/csp/YYYY/, output/netcdf/GLOB/JPL/MUR/v4/YYYY/DOY[nrt]/
    ├── cache/                            # mrva.cache_dir (writable scratch + seasonal25 cache)
    └── logs/
```

**Create directories:**
```bash
mkdir -p testing/static-resources/{grids,mat/p01,mat/p011,seasonal,landice,L4}
mkdir -p testing/preprocessing/inputs/l2p/{AMSR2R,MODISA,MODIST,AVMTAG,AVMTBG}
mkdir -p testing/preprocessing/output/{landice-p01,landice-p011,iquam}
mkdir -p testing/preprocessing/output/l2p/{AMSR2R,MODISA,MODIST,AVMTAG,AVMTBG}
mkdir -p testing/mrva/{output/csp,output/netcdf,cache,logs}
```

Populate `testing/static-resources/` per [STATIC_DATA.md](STATIC_DATA.md) before running anything — nothing in the pipeline generates those files.

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

The flags below are the actual `run_mur_pipeline.py` argparse surface — run `uv run mur-pipeline --help` for the authoritative, always-current version.

```
usage: mur-pipeline --config CONFIG [--date DATE] [-p PROCESS_DAYS] [--all-stages]
                     [--preprocess-only] [--debug] [--netrc-path PATH]
                     [--execute STAGE] [--force-nrt] [--keep-containers]
                     [--force-date-download] [--deep-purge] [--sensors LIST]
                     [--collection NAME] [--deep-sync-days N]

required arguments:
  --config CONFIG          Path to config.json file

optional arguments:
  --date DATE               Simulate running on this date (YYYY-MM-DD); default: actual today
  -p, --process-days DAYS   Analysis day offset(s) from run day: single ('-1') or range ('-9:-1'); default: -1 (yesterday/NRT)
  --all-stages               Process full 9-day window (equivalent to --process-days -9:-1)
  --preprocess-only          Run landice/iquam/l2p only, skip MRVA
  --debug                    Enable debug logging
  --netrc-path PATH          Path to .netrc file (default: ~/.netrc)
  --execute STAGE             Run only these stage(s): landice, l2p-download, l2p, iquam, mrva, purge
                              (comma-separated or repeatable; 'l2p-download' must be requested
                              explicitly -- it's never part of a default run, see below)
  --force-nrt                 Force NRT mode for all dates, overriding automatic REA/NRT detection
  --keep-containers           Don't auto-remove containers after execution (debugging)
  --force-date-download       Use bounded ±day_range downloads instead of incremental mode (testing/backfill)
  --deep-purge                Purge stage sweeps every year subdirectory using the 9-day scan window
                              (implies --execute purge if no --execute given)
  --sensors LIST               Filter to specific sensors for L2P stages (comma-separated)
  --collection NAME             Filter a single AMSR2R collection when --sensors AMSR2R is given
  --deep-sync-days N            l2p-download re-queries the trailing N days instead of using the
                                 incremental watermark (recovers orphaned granules; recommended: 9)
```

**No `--verbose`/`-v` flag exists** (use `--debug`), and there is no separate `--run-mrva` flag — MRVA runs by default alongside the other stages unless you pass `--preprocess-only` or a narrower `--execute` list.

**L2P downloading is decoupled from processing, matching production.** `run_mur_pipeline.py` never downloads L2P granules on its own — the `l2p` stage only turns whatever's already on disk (under `l2p.input_dir`) into BIC files. Downloads happen via the separate `l2p-download` stage (`--execute l2p-download`), normally triggered by cron (see `run_l2p_download_cron.sh`/`run_l2p_deepsync_cron.sh` at the repo root) — make sure that's actually running (or backfill manually with `--execute l2p-download --force-date-download` for a specific date) before expecting `l2p`/`mrva` to have anything to process.

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

**Direct container execution:** every static input is an individually bind-mounted file and named flag — see [landice/README.md](../landice/README.md) for the full six-file layout and [STATIC_DATA.md](STATIC_DATA.md) for where those files come from.

```bash
docker run --rm \
  --platform linux/amd64 \
  --shm-size=512M \
  -v /nas2/static-resources/grids/maskGLOBp01deg.gds:/input/landmask-p01.gds:ro \
  -v /nas2/static-resources/mat/p01/saf2north.mat:/input/gridindex-north-p01.mat:ro \
  -v /nas2/static-resources/mat/p01/saf2south.mat:/input/gridindex-south-p01.mat:ro \
  -v /nas2/static-resources/grids/maskGlob1km.gds:/input/landmask-p011.gds:ro \
  -v /nas2/static-resources/mat/p011/saf2north.mat:/input/gridindex-north-p011.mat:ro \
  -v /nas2/static-resources/mat/p011/saf2south.mat:/input/gridindex-south-p011.mat:ro \
  -v /nas2/output/p011:/output/p011 \
  -v /nas2/output/p01:/output/p01 \
  mur-landice:latest \
  --year 2025 --doy 042 \
  --landmask-p01-file /input/landmask-p01.gds \
  --gridindex-north-p01-file /input/gridindex-north-p01.mat \
  --gridindex-south-p01-file /input/gridindex-south-p01.mat \
  --landmask-p011-file /input/landmask-p011.gds \
  --gridindex-north-p011-file /input/gridindex-north-p011.mat \
  --gridindex-south-p011-file /input/gridindex-south-p011.mat
```

**Output:**
```
/nas2/output/p01/2025/landiceP01_2025_042.gds.gz    - Land/ice mask (0.01°, used by MUR v4)
/nas2/output/p01/2025/Global_ice_2025_042.bip        - Ice SST points (0.01°)
/nas2/output/p011/2025/landice_2025_042.gds.gz       - Land/ice mask (0.011°, legacy)
/nas2/output/p011/2025/Global_ice_2025_042.bip        - Ice SST points (0.011°)
```

**Runtime:** 2-5 minutes

### iQUAM Buoy Processing

**Direct container execution:** every input is a named flag; there is no positional or "use defaults" form, and no cache mount — see [iquam/README.md](../iquam/README.md) for the full parameter list.

```bash
docker run --rm \
  --platform linux/amd64 \
  --shm-size=512M \
  -v /nas2/output/iquam:/data/output/iquam \
  -v /nas2/logs/iquam:/data/logs \
  mur-iquam:latest \
  --year 2025 --doy 042 --mode nrt --reference-date 2025-02-12 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

**Output:**
```
/nas2/output/iquam/2025/Global_IQUAM0_2025_042.bii
```

**Runtime:** 2-5 minutes per day (no cache — every run downloads fresh)

### L2P Satellite Processing

**Direct container execution:** every input is a named flag; `--granules-manifest` replaces the old bind-mounted input directory with a JSON manifest listing exactly which granule files this run needs (local path or `s3://` href per entry) — see [l2p/README.md](../l2p/README.md) for the manifest schema. `run_mur_pipeline.py` builds this manifest automatically from `l2p.input_dir`; the example below is for manual/debug use.

```bash
docker run --rm \
  --platform linux/amd64 \
  --shm-size=512M \
  -v /nas2/preprocessing/inputs/l2p/MODISA:/nas2/preprocessing/inputs/l2p/MODISA:ro \
  -v /tmp/manifest.json:/tmp/manifest.json:ro \
  -v /nas2/preprocessing/output/l2p/MODISA:/data/output \
  mur-l2p:latest \
  --sensor MODISA --region Global --year 2025 --doy 042 --rewrite 1 \
  --granules-manifest /tmp/manifest.json
```

**Output:**
```
/nas2/preprocessing/output/l2p/MODISA/2025/Global_MODISA_2025_042.bic.gz
```

**Runtime:**
- AMSR2R: 5-10 minutes
- MODISA: 10-20 minutes
- MODIST: 10-20 minutes
- AVMTBG: 5-10 minutes

**In practice, use `run_mur_pipeline.py`** rather than invoking the container directly — it downloads/tracks granules, builds the manifest, and handles all sensors:

```bash
# All active_sensors for one day
uv run mur-pipeline --config config.json --date 2025-02-11 --execute l2p

# One sensor only
uv run mur-pipeline --config config.json --date 2025-02-11 --execute l2p --sensors MODISA
```

### MRVA Analysis

**Direct container execution:** every input is an explicit named flag — three static-resource files, three per-day landice-output files, one `--sensor-inputs-manifest` covering the BIC + iQuam fan-in (unified, both are the same shape internally), and two optional flags. See [mrva/README.md](../mrva/README.md) for the full flag list and [STATIC_DATA.md](STATIC_DATA.md) for where the static files come from. Output directories stay fixed bind mounts, unchanged from before.

```bash
docker run --rm \
  --platform linux/amd64 \
  --memory=72g --shm-size=2g \
  -v /nas2/static-resources:/nas2/static-resources:ro \
  -v /nas2/preprocessing/output:/nas2/preprocessing/output:ro \
  -v /tmp/manifest.json:/tmp/manifest.json:ro \
  -v /nas2/mrva/output/csp:/data/output/csp \
  -v /nas2/mrva/output/netcdf:/data/output/netcdf \
  -v /nas2/mrva/cache:/data/cache \
  -v /nas2/mrva/logs:/data/logs \
  mur-mrva:latest \
  --year 2025 --doy 042 --mode nrt \
  --polar-cap-edge-file /nas2/static-resources/landice/CylinderP01_edge.bip \
  --seasonal-file /nas2/static-resources/seasonal/mur_042.nc \
  --landice-ice-p011-file /nas2/preprocessing/output/landice-p011/2025/Global_ice_2025_042.bip \
  --landice-grid-p01-file /nas2/preprocessing/output/landice-p01/2025/landiceP01_2025_042.gds.gz \
  --landice-icefiles-p011-file /nas2/preprocessing/output/landice-p011/2025/icefiles_2025_042.txt \
  --sensor-inputs-manifest /tmp/manifest.json \
  --l4-reference-root /nas2/static-resources/L4
```

Optional flags: `--sensors` (comma-separated, default all configured), `--mur25-grid-file` (absent → skip MUR25 generation), `--prior-csp-file` (absent → build the reference field from scratch), `--l4-reference-root` (absent → no L4 bootstrap fallback in `trimbip3a`; `run_mur_pipeline.py` passes it only when the directory exists), `--debug`.

**Output:**
```
testing/mrva/output/csp/2025/2025021109_MRVA4_Global.c00 .. .c11, .u06-.u08
testing/mrva/output/netcdf/GLOB/JPL/MUR/v4/2025/042nrt/20250211090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc
```
(`nrt` suffix on the DOY directory for NRT runs; absent for REA. NRT output is always rewritten; REA output is kept if it already exists.)

**Runtime:** 30-90 minutes (NRT), longer for REA (coarser starting scale, L0=2 vs L0=6).

**In practice, use `run_mur_pipeline.py`** — it resolves every static/landice-output file and builds the sensor-inputs manifest automatically:

```bash
uv run mur-pipeline --config config.json --date 2025-02-11 --execute mrva --keep-containers
```

`--keep-containers` is worth using on a first attempt against real data — if MRVA fails, the container isn't auto-removed, so `docker logs <container_name>` (name printed at startup, `mrva_<year>_<doy>_<timestamp>`) shows the actual MATLAB error instead of just an exit code.

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

# Inside container, run the compiled executable directly — it takes the
# same positional order entrypoint.sh's build_command assembles from the
# named flags: six static files (p01 landmask, p01 gridindex north/south,
# p011 landmask, p011 gridindex north/south), then the two output dirs,
# then year, then doy
ls /opt/landice/bin
/opt/landice/bin/LandiceProcessor \
  /input/landmask-p01.gds /input/gridindex-north-p01.mat /input/gridindex-south-p01.mat \
  /input/landmask-p011.gds /input/gridindex-north-p011.mat /input/gridindex-south-p011.mat \
  /output/p011 /output/p01 2025 042
```

**MRVA's compiled binary takes a different form** — `entrypoint.sh` resolves every named flag, writes them into one generated JSON config file, and invokes `MrvaProcessor <year> <doy> <mode> <config_file_path>` (just 4 positional args, not one per input — see `mrva/bin/entrypoint.sh`'s `write_config()`). To debug MRVA directly, either let `entrypoint.sh` build the config file for you and only override the final `exec`, or construct the JSON yourself matching `mrva4com_container.m`'s expected fields (`polar_cap_edge_file`, `seasonal_file`, `landice_ice_p011_file`, `landice_grid_p01_file`, `landice_icefiles_p011_file`, `sensor_inputs_root`, `l4_reference_root`, optional `mur25_grid_file`/`prior_csp_file`/`sensors`/`debug`) and pass its path directly:
```bash
docker run -it --rm --entrypoint /bin/bash mur-mrva:latest
/opt/mrva/bin/MrvaProcessor 2025 042 nrt /tmp/mrva_config.json
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

**Current Status:** All four stages (Land/Ice, iQUAM, L2P, MRVA) are operational and produce a full NetCDF4 MUR product via `run_mur_pipeline.py`. Every container takes its inputs as explicit named flags (local path or `s3://` href, uniformly) rather than bind-mounted directories — see `INPUT_CONTRACT.md` for the full design and `documentation/MAAP_EXECUTION.md` for the equivalent MAAP-side status.

---

## References

- [OVERVIEW.md](OVERVIEW.md) - System architecture overview
- [DATA_LIFECYCLE.md](DATA_LIFECYCLE.md) - Data flow and caching
- [SENSOR_ADAPTATION.md](SENSOR_ADAPTATION.md) - Adding new sensors
- [STATIC_DATA.md](STATIC_DATA.md) - Static/semi-static reference file layout and explicit-flag resolution
- [MAAP_EXECUTION.md](MAAP_EXECUTION.md) - MAAP (cloud) execution status, as distinct from this document's local-Docker focus
- Component READMEs:
  - [landice/README.md](../landice/README.md)
  - [iquam/README.md](../iquam/README.md)
  - [l2p/README.md](../l2p/README.md)
  - [mrva/README.md](../mrva/README.md)

---

*Last Updated: 2026-09-03*
*Documentation Version: 2.0 (All four stages operational)*
