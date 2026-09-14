# AGENTS.md

## Project Overview

The NASA MUR (Multi-scale Ultra-high Resolution) workflow processes sea surface temperature (SST) data to deliver high-resolution products for Earth system science, weather forecasting, and climate research. The system consists of three main processing components that work together in a coordinated pipeline.

## Development Environment

### Prerequisites
- Python 3.12+
- MATLAB R2021b or later
- NASA Earthdata account with .netrc credentials
- Docker (optional, for containerized execution)

### Python Dependencies
- `earthaccess` - NASA Earthdata API access
- `fsspec` - File system operations
- Standard library: argparse, datetime, json, logging, pathlib, subprocess

### Authentication Setup
Create `.netrc` file in home directory:
```
machine urs.earthdata.nasa.gov
    login <your-username>
    password <your-password>
```
Set permissions: `chmod 600 ~/.netrc`

## Architecture & Components

### 1. InputGen - Coordination Generator
**Location:** `inputgen/`
**Purpose:** Generates JSON coordination files for parallel execution
**Outputs:** 
- `landice.json` - 9-day date ranges for land ice processing
- `l2p.json` - 12-day date ranges per sensor for L2P processing

### 2. Land Ice - Boundary Processor  
**Location:** `landice/`
**Purpose:** Prepares landmask and sea ice boundary data
**Key Features:**
- Processes OSI SAF sea ice datasets
- Supports p01 (0.01°) and p011 (0.011°) grid resolutions
- Generates MATLAB processing scripts
- Parallelizable by day

### 3. L2P Sensors - Satellite Data Processor
**Location:** `l2p/`
**Purpose:** Downloads and processes Level 2P satellite sensor data
**Supported Sensors:**
- AMSR2R - AMSR2-REMSS with 12-day range
- AVMTBG - AVHRRMTB_G-NAVO with 12-day range  
- MODISA - MODIS Aqua with 12-day range
- MODIST - MODIS Terra with 12-day range
**Features:** Fully parallelizable by sensor and day

## Build & Deployment

### Docker Build
Build every module with `build_module.sh` from the `mur/` directory — it builds the
`mur-matlab-base:r2024b` image if missing, checks `network.lic`, sets the platform and
build context, and applies the `mur-<module>:latest` tags the pipeline config expects:
```bash
./build_module.sh all            # iquam, l2p, landice, mrva
./build_module.sh l2p            # single module
./build_module.sh mrva --debug   # symbols + bounds checking
```

**Advanced — manual build:** only when `build_module.sh` doesn't fit (custom tags, CI,
Dockerfile debugging). The build context must be the parent `mur/` directory so `common/`
is reachable:
```bash
cd mur/l2p
docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..
```
See [documentation/PIPELINE_CONFIGURATION.md](documentation/PIPELINE_CONFIGURATION.md#manual-builds-advanced).

### Docker Execution
```bash
# L2P Component
docker run --rm \
  -v /path/to/input:/data/input \
  -v /path/to/output:/data/output \
  -v $HOME/.netrc:/home/matlab/.netrc:ro \
  mur-l2p:latest \
    -s AMSR2R -d 220 -y 2025 \
    -i /data/input -o /data/output \
    -c /data/input/config.json -w

# Land Ice Component  
docker run --rm \
  -v /path/to/data:/mnt/data \
  mur-landice:latest \
    -i /mnt/data/input -o /mnt/data/output \
    -y 2025 -d 225
```

## Key Commands

### Generate Coordination Files
```bash
python inputgen/src/execute_inputgen.py \
  -o /path/to/output \
  -c inputgen/src/config.json
```

### Process Land Ice Data
```bash
python landice/src/execute_landice.py \
  -i /path/to/input \
  -o /path/to/output \
  -y 2025 \
  -d 225  # Day of year
```

### Process L2P Sensor Data
```bash
python l2p/src/execute_l2p.py \
  -s AMSR2R \           # Sensor name
  -d 220 \              # Day of year
  -y 2025 \             # Year
  -i /path/to/input \
  -o /path/to/output \
  -c l2p/src/config.json \
  -w                    # Download data
```

## Code Organization

```
mur/
├── inputgen/
│   ├── src/
│   │   ├── execute_inputgen.py  # Main coordination generator
│   │   └── config.json          # Sensor configurations
│   └── README.md
├── landice/
│   ├── src/
│   │   ├── execute_landice.py   # Main land ice processor
│   │   ├── landice_template.m   # MATLAB template
│   │   └── *.m                  # MATLAB utilities
│   ├── data_creation/           # Grid-specific MATLAB scripts
│   │   ├── p01/                 # 0.01° grid
│   │   └── p011/                # 0.011° grid
│   ├── tests/
│   └── README.md
└── l2p/
    ├── src/
    │   ├── execute_l2p.py        # Main L2P processor
    │   ├── l2p_template.m        # MATLAB template
    │   └── *.m                  # MATLAB utilities
    ├── tests/
    └── README.md
```

## Testing

### Test Execution Scripts
```bash
# Test L2P processing
python l2p/tests/test_execute_l2p.py -c l2p/tests/config_test.json

# Test Land Ice processing  
python landice/tests/test_execute_landice.py -c landice/tests/config_test.json
```

### Configuration Files
- Production: `*/src/config.json`
- Testing: `*/tests/config_test.json`

## Performance Benchmarks

- **InputGen:** ~2.5 minutes execution time
- **L2P Processing:** ~32.5 minutes (fully parallelized)
- **Land Ice:** Varies by day range, parallelizable

## Environment Variables

### OSI-SAF Endpoints (Land Ice)

OSI-SAF's anonymous FTP is dead (`ftp://osisaf.met.no` times out). These are
the HTTPS THREDDS endpoints; the variables keep their `_FTP_` names because
they are part of the container's published interface.

```bash
export OSISAF_FTP_ARCHIVE="https://thredds.met.no/thredds/fileServer/osisaf/met.no/ice/amsr2_conc"
export OSISAF_FTP_PROD="https://thredds.met.no/thredds/fileServer/osisaf/met.no/ice/amsr2_conc"
# OSISAF_FTP_REPROCESSED (pre-2009 dates) has no default and no verified
# HTTPS equivalent — set it explicitly only for historical reprocessing.
```

That tree serves AMSR3 files from 2026-08-31 onward despite the `amsr2_conc`
name; `landice/src/readosisafice.m` picks the filename token by date, and the
cutover is overridable with `OSISAF_AMSR3_START=YYYYMMDD`.

## Workflow Execution Order

1. **InputGen** - Generate coordination files first
2. **Parallel Execution:**
   - Land Ice operations (using landice.json dates)
   - L2P sensor operations (using l2p.json sensor/date combinations)
3. **MRVA Processing** - Consumes outputs from Land Ice and L2P

## Important Notes

- All Python scripts use absolute paths for file operations
- MATLAB scripts are generated dynamically from templates
- Parallel execution is coordinated through JSON files
- Downloaded L2P data is cleaned up after processing to save space
- Each component can run independently with proper inputs

## Debugging Tips

- Check logs for execution times and parameter values
- Verify .netrc credentials for Earthdata access
- Ensure MATLAB path is correctly configured
- Monitor disk space when processing large datasets
- Use test configurations for validation before production runs