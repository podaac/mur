# MUR Static Data Requirements

This document describes all static data files required by the MUR processing pipeline. Static data refers to files that do not change with processing date and are used as reference inputs across all processing runs.

## Table of Contents

1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Grid Mask Files](#grid-mask-files)
4. [OSI-SAF Transformation Matrices](#osi-saf-transformation-matrices)
5. [Seasonal Climatology](#seasonal-climatology)
6. [L4 Reference Data](#l4-reference-data)
7. [Polar Cap Edge Data](#polar-cap-edge-data)
8. [Data Sources](#data-sources)

## Overview

Static data is stored in the `static-resources/` directory on disk — the layout documented below never changes. Unlike dynamic inputs (L2P, iQUAM, land/ice), these files are:

- **Immutable:** Never modified during processing
- **Resolution-specific:** Different files for 0.01° vs 0.011° grids
- **Shared across modules:** Used by both landice and MRVA containers

**Both landice and MRVA now take every static file as an individually resolved, explicitly-named flag** (`--landmask-p01-file`, `--polar-cap-edge-file`, `--seasonal-file`, etc. — see [landice/README.md](../landice/README.md), `mrva/bin/entrypoint.sh`); nothing is discovered by scanning a directory or bind-mounting a whole `static-resources/` tree. MRVA additionally takes three per-day landice-output files (`--landice-ice-p011-file`, `--landice-grid-p01-file`, `--landice-icefiles-p011-file`) and a `--sensor-inputs-manifest` covering its per-sensor BIC/iQuam fan-in (see `docs/superpowers/specs/2026-07-27-explicit-input-contract-design.md` section 3) the same way.

**Local paths or S3 hrefs, uniformly.** Every flag value may be either a local filesystem path (bind-mounted for local `docker run`) or an `s3://` href (MAAP, or any S3-accessible environment) — `entrypoint.sh` sources a shared helper (`common/bin/localize.sh`) that fetches `s3://` values to local scratch space via `aws s3 cp` before MATLAB runs; local paths pass through unchanged. This is why the flags are described as "explicitly-named" rather than "bind-mounted": bind-mounting is how the local orchestrator (`run_mur_pipeline.py`) happens to supply a local path, not a requirement of the flag contract itself. See `docs/superpowers/specs/2026-07-27-explicit-input-contract-design.md` section 4 for the full rationale (why this has to happen inside the container rather than in Python).

**MRVA's `static-resources/` mount is now genuinely read-only.** `makeMUR25_container.m`'s seasonal climatology cache (`seasonal25/mur_###.mat`) previously wrote back into `static_resources_root` at runtime — this was fixed to write into the writable `cache_dir` instead, matching its sibling ice-cache's already-correct pattern.

**One directory-shaped exception:** `--l4-reference-root` (the optional GHRSST L4 bootstrap reference, only used when no prior-day coefficient exists) is a directory tree, not a single file. `common/bin/localize.sh` doesn't do recursive S3 sync (`aws s3 cp` without `--recursive`), so this flag is bind-mounted/passed through as-is locally; real S3-recursive localization for this specific input is not implemented.

### Configuration

`run_mur_pipeline.py` resolves landice's six files from a single root path, configured in `config.json`:

```json
{
  "landice": {
    "static_resources_dir": "testing/static-resources"
  },
  "mrva": {
    "static_resources_dir": "testing/static-resources"
  }
}
```

(`landice.static_resources_dir` was named `landice.input_dir` before landice's explicit-input-flags conversion — the value is the same root, just the key was renamed for clarity now that it's resolved into six explicit files rather than bind-mounted whole.)

## Directory Structure

```
static-resources/
├── grids/                    # Land/sea mask files
│   ├── maskGLOBp01deg.gds    # 0.01° resolution (36000×17999)
│   ├── maskGlob1km.gds       # 0.011° resolution (1km)
│   ├── Glob1km.mask          # Alternative 1km mask format
│   └── MUR25grid.gds         # 0.25° resolution (1440×720) - for MUR25 product
│
├── mat/                      # MATLAB transformation matrices
│   ├── landindexNH.mat       # Northern hemisphere land indices
│   ├── landindexSH.mat       # Southern hemisphere land indices
│   ├── latlonOSISAFnh.mat    # OSI-SAF NH lat/lon grid
│   ├── latlonOSISAFsh.mat    # OSI-SAF SH lat/lon grid
│   ├── p01/                  # For 0.01° resolution
│   │   ├── saf2north.mat     # NH ice→grid mapping (~152 MB)
│   │   └── saf2south.mat     # SH ice→grid mapping (~127 MB)
│   └── p011/                 # For 0.011° resolution
│       ├── saf2north.mat     # NH ice→grid mapping (~126 MB)
│       └── saf2south.mat     # SH ice→grid mapping (~111 MB)
│
├── seasonal/                 # MUR seasonal climatology
│   ├── mur_001.nc            # Day 1 climatology
│   ├── mur_002.nc            # Day 2 climatology
│   ├── ...
│   └── mur_365.nc            # Day 365 climatology
│
├── L4/                       # L4 reference SST (optional)
│   └── GLOB/
│       └── NCDC/
│           └── AVHRR_OI/
│               └── {year}/{day}/*.bz2
│
└── landice/                  # Polar cap edge data
    └── CylinderP01_edge.bip  # Polar stereographic edge (~35 MB)
```

## Grid Mask Files

### Purpose

Grid mask files define the land/sea/lake classification for each pixel in the output grid. They are used by:

- **landice module:** As base mask to add ice flags
- **MRVA module:** For output NetCDF generation (when ice not included)

### Files

| File | Resolution | Dimensions | Size | Description |
|------|------------|------------|------|-------------|
| `maskGLOBp01deg.gds` | 0.01° | 36000×17999 | 648 MB | Primary MUR grid |
| `maskGlob1km.gds` | 0.011° | ~32727×16363 | 537 MB | 1km grid variant |
| `Glob1km.mask` | 0.011° | ~32727×16363 | 1 GB | Alternative format |
| `MUR25grid.gds` | 0.25° | 1440×720 | ~1 MB | MUR25 product grid |

### MUR25 Grid File

The `MUR25grid.gds` file is required for generating the MUR25 (0.25-degree) product. This is a lower-resolution "sibling" product that is derived from the same MRVA analysis as the full MUR SST.

**Product Comparison:**

| Product | Resolution | Grid Size | Filename Pattern |
|---------|------------|-----------|------------------|
| MUR (Full) | 0.01° | 36000×17999 | `...-MUR-GLOB-...fv04.1.nc` |
| MUR25 | 0.25° | 1440×720 | `...-MUR25-GLOB-...fv04.2.nc` |

**To obtain the MUR25 grid file:**

1. Copy from production: `/home/tmchin/grids/MUR25grid.gds`
2. Or generate by downsampling the 0.01° mask using the `MURto25` function

**Note:** If the MUR25 grid file is not present, the container workflow will skip MUR25 generation but still produce the full-resolution MUR product.

### Mask Value Encoding

```
BASE VALUES:
  1 (0001b) = Open sea
  2 (0010b) = Land
  3 (0011b) = Coast/shore
  5 (0101b) = Open lake
  7 (0111b) = Lake shore

WITH ICE (bit 3 added):
  9  (1001b) = Open sea with ice
  11 (1011b) = Coast with ice
  13 (1101b) = Open lake with ice
```

### File Format

Binary Fortran unformatted file with structure:
```
Record 1: [ii, jj]           - Grid dimensions (int32)
Record 2: [mask, mlon, mlat] - Mask array (int8) + coordinates (float32)
```

## OSI-SAF Transformation Matrices

### Purpose

These MATLAB `.mat` files contain pre-computed index mappings that transform OSI-SAF polar stereographic ice concentration data onto the MUR cylindrical grid.

### Files

| Directory | File | Description |
|-----------|------|-------------|
| `mat/` | `landindexNH.mat` | NH land pixel indices |
| `mat/` | `landindexSH.mat` | SH land pixel indices |
| `mat/` | `latlonOSISAFnh.mat` | OSI-SAF NH coordinate grid |
| `mat/` | `latlonOSISAFsh.mat` | OSI-SAF SH coordinate grid |
| `mat/p01/` | `saf2north.mat` | NH ice→0.01° grid mapping |
| `mat/p01/` | `saf2south.mat` | SH ice→0.01° grid mapping |
| `mat/p011/` | `saf2north.mat` | NH ice→0.011° grid mapping |
| `mat/p011/` | `saf2south.mat` | SH ice→0.011° grid mapping |

### Used By

- `landice/src/makeicefiles.m` - Ice concentration gridding

## Seasonal Climatology

### Purpose

Daily MUR SST climatology files provide seasonal reference values for quality control and anomaly computation. Each file contains the multi-year average SST for a specific day of year.

### Files

- **Location:** `seasonal/mur_###.nc` where `###` is day-of-year (001-365)
- **Format:** NetCDF with `sst`, `lon`, `lat` variables
- **Coverage:** Global, 0.01° resolution
- **Count:** 365 files (day 366 uses day 365)

### Used By

- `mrva/src/matlab/io/readSeasonal.m` - Seasonal climatology lookup

### Source

Generated from multi-year MUR SST archive (typically 5+ years of data).

## L4 Reference Data

### Purpose

L4 GHRSST reference SST data is used as a background field for the "trimbip" quality control step. This step removes outliers from sensor data by comparing against a smooth reference field.

### When It's Needed

| Scenario | L4 Required? |
|----------|--------------|
| First day of processing | **Yes** - No previous MUR coefficient exists |
| Consecutive daily runs | **No** - Uses previous day's `.c06` coefficient |
| After processing gaps | **Only if** previous day's coefficient is missing |

### How It Works

The `trimbip3a.m` function checks for a previous MUR coefficient file:

```matlab
if length(MURcsp),  %% use MUR reference:
  refcspfile='MUR.csp';
  eval(sprintf('!ln -sf %s %s',MURcsp,refcspfile));
else,  %% use L4 reference:
  % Look for L4 GHRSST file...
  dirname=sprintf('%s/GLOB/NCDC/AVHRR_OI/%04d/%03d/*fv02*.bz2',...
```

### Directory Structure

```
L4/
└── GLOB/
    └── NCDC/
        └── AVHRR_OI/
            └── 2025/           # Year
                └── 314/        # Day of year
                    └── 20251110-NCEI-L4LRfnd-GLOB-...fv02.0.nc.bz2
```

### Data Source

**NOAA NCEI AVHRR Optimum Interpolation (OI) SST**

- **Product:** GHRSST Level 4 AVHRR_OI Global Blended Sea Surface Temperature Analysis
- **Short Name:** `AVHRR_OI-NCEI-L4-GLOB-v2.0` or `AVHRR_OI-NCEI-L4-GLOB-v2.1`
- **Resolution:** 0.25° (25 km)
- **Provider:** NOAA National Centers for Environmental Information (NCEI)

**Download Sources:**

1. **PO.DAAC (NASA):**
   - https://podaac.jpl.nasa.gov/dataset/AVHRR_OI-NCEI-L4-GLOB-v2.1
   - Use `podaac-data-subscriber` tool

2. **NOAA NCEI:**
   - https://www.ncei.noaa.gov/products/optimum-interpolation-sst

3. **GHRSST LTSRF:**
   - https://www.ghrsst.org/

### Alternative L4 Products

The code supports other L4 products (commented out in `trimbip3a.m`):

```matlab
L4list={  % choose only one:
'RV1','GLOB/NCDC/AVHRR_OI','*fv02*.bz2','bzcat'    % <-- Active
%'RV2','GLOB/NCDC/AVHRR_AMSR_OI','*fv02*.bz2','bzcat'
%'OSTIA','GLOB/UKMO/OSTIA','*fv02*.bz2','bzcat'
%'ODYSSEA','GLOB/EUR/ODYSSEA','*fv02*.bz2','bzcat'
%'K10','GLOB/NAVO/K10_SST','*fv02*.bz2','bzcat'
%'ABOM','GLOB/ABOM/GAMSSA_28km/','*fv02*.bz2','bzcat'
};
```

### Practical Guidance

**For Testing:**

If you have a previous coefficient file (e.g., `2025111009_MRVA4_Global.c06`), you can run subsequent days without L4 data.

**For Production Bootstrap:**

1. Download one day of AVHRR_OI data for your start date
2. Run MRVA for that date (will use L4 as reference)
3. Subsequent days will use the previous coefficient

**Example Download:**

```bash
# Using podaac-data-subscriber
podaac-data-subscriber \
  -c AVHRR_OI-NCEI-L4-GLOB-v2.1 \
  -d ./L4/GLOB/NCDC/AVHRR_OI \
  --start-date 2025-11-10 \
  --end-date 2025-11-10
```

## Polar Cap Edge Data

### Purpose

The polar cap edge file (`CylinderP01_edge.bip`) defines the boundary region near the poles where cylindrical projection transitions to the polar stereographic region. This is used during MRVA analysis.

### File

| File | Size | Format |
|------|------|--------|
| `landice/CylinderP01_edge.bip` | ~35 MB | Binary BIP format |

### Used By

- `mrva/src/matlab/preprocessing/makeref.m` - Reference field generation

## Data Sources

### Where to Obtain Static Data

| Data Type | Source | Access |
|-----------|--------|--------|
| Grid masks | JPL MUR team | Internal distribution |
| OSI-SAF matrices | Pre-computed from OSI-SAF grids | Generated once |
| Seasonal climatology | Derived from MUR archive | Multi-year average |
| L4 AVHRR_OI | PO.DAAC / NOAA NCEI | Public download |
| Polar cap edge | JPL MUR team | Internal distribution |

### Production vs Testing

In the original production environment, static data resided on shared NAS storage:
- `/store/ghrsst/open/data/L4/` - GHRSST L4 archive
- `/home/tmchin/grids/` - Grid mask files
- `/home/tmchin/nas/` - Seasonal and other static data

For containerized deployment, all static data is consolidated under `static-resources/` and mounted into containers.

## Verification

To verify static data is correctly installed:

```bash
# Check grid masks
ls -la testing/static-resources/grids/
# Should show: maskGLOBp01deg.gds (~648 MB), maskGlob1km.gds (~537 MB)

# Check transformation matrices
ls -la testing/static-resources/mat/p01/
# Should show: saf2north.mat (~152 MB), saf2south.mat (~127 MB)

# Check seasonal climatology
ls testing/static-resources/seasonal/ | wc -l
# Should show: 365

# Check L4 data (if needed)
ls testing/static-resources/L4/GLOB/NCDC/AVHRR_OI/2025/314/
# Should show: *fv02*.bz2 file for your start date
```

## Related Documentation

- [PIPELINE_CONFIGURATION.md](PIPELINE_CONFIGURATION.md) - Pipeline setup and operation
- [LANDICE_ENCODING.md](LANDICE_ENCODING.md) - Land/ice mask encoding details
- [ALGORITHM_FLOW.md](ALGORITHM_FLOW.md) - Overall algorithm description
