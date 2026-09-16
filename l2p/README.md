# MUR L2P Satellite SST Processing Module

## Overview

The L2P (Level 2 Preprocessed) module processes satellite-derived sea surface temperature observations from multiple sensors for assimilation into the Multi-scale Ultra-high Resolution (MUR) SST analysis system.

**Containerized Deployment:** This application is containerized using Docker with a multi-stage build process following the same pattern as the IQUAM module - MATLAB compilation in stage 1, MATLAB Runtime-only execution in stage 2.

## What This Module Produces

**Primary Output:** Daily binary files (`.bic.gz` format) containing satellite SST observations with bias and error metadata

**Processing Steps:**

1. **Read** L2P/L3U format NetCDF files with SST, bias, and quality metadata
2. **Filter** by confidence/proximity thresholds (sensor-specific)
3. **Time Translation** from reference time to hours relative to analysis day
4. **Format Conversion** to compact BIC (Binary Input with Confidence) format
5. **Compress** output files with gzip

**Note:** Downloads are handled separately in production (cron jobs using podaac-data-subscriber), not by this container.

**Output Characteristics:**

- **Format:** Fortran-compatible binary (`.bic.gz`)
- **Size:** ~50-500 MB per sensor per day (compressed)
- **Content:** SST, lon/lat, hour, bias, RMS error, quality flag
- **Coverage:** Sensor-dependent (swath data for polar orbiters)

## Supported Sensors

| Sensor | Satellite | Type | Collection | Stability |
|--------|-----------|------|------------|-----------|
| **AMSR2R** | GCOM-W1 | Microwave | AMSR2-REMSS-L2P-v8.2 / RT | 2 days |
| **AVMTBG** | MetOp-B | Infrared | AVHRRMTB_G-NAVO-L2P-v2.0 | 2 days |
| **MODISA** | Aqua | Infrared | MODIS_A-JPL-L2P-v2019.0 | 2 days |
| **MODIST** | Terra | Infrared | MODIS_T-JPL-L2P-v2019.0 | 3 days |

**Microwave sensors** (AMSR2R) provide all-weather capability but at coarser resolution.
**Infrared sensors** (MODIS, AVHRR) provide high resolution but are affected by clouds.

## Architecture

### Production-Matching Interface

This containerized module **exactly matches the production nrtMRVA.py calling pattern**, using a pure MATLAB wrapper compiled into a standalone executable. The container exposes the same 7-argument `l2p2bic()` signature used in production:

```
l2p2bic(sensor, region, indir, bicdir, year, day, rewrite)
```

**Benefits:**

- **Production parity** - Same interface as nrtMRVA.py (lines 350-363)
- **No Python** - Pure MATLAB Runtime (no integration issues)
- **Smaller image** - ~2.5 GB (vs ~8 GB with Python)
- **Flexible paths** - No hardcoded directories
- **Separation of concerns** - Downloads handled separately (like production cron jobs)

### File Structure

```
l2p/
├── Dockerfile              # Multi-stage build: compile → runtime
├── README.md              # This file
├── requirements.txt       # REMOVED - No longer needed
└── src/
    ├── l2p_wrapper.m      # NEW: Main wrapper (compiled entry point)
    ├── l2p2bic.m          # Core L2P → BIC conversion
    ├── SensorTable.m      # Sensor-specific configuration
    ├── readL2Pboth.m      # L2P swath reader
    ├── readL3UasL2P.m     # L3U gridded reader
    ├── readL3UasL2Pviirso.m # VIIRS-specific reader
    └── writebic.m         # BIC format writer

Common dependencies (copied during build):
    common/julian.m        # Date conversion utilities
    common/fortwrite.m     # Fortran binary I/O
```

**Obsolete files (can be removed):**
- `execute_l2p.py` - Replaced by pure MATLAB `l2p_wrapper.m`
- `l2p_template.m` - No longer needed (direct function calls)
- `requirements.txt` - No Python dependencies
- `config.json` - Not used in production (config embedded in wrapper)

**New files added:**
- `l2p_wrapper.m` - Production-matching wrapper with 7-argument interface

## Docker Build and Run Instructions

### Build the Image

From the **l2p directory** with parent context:

```bash
cd /path/to/mur/l2p
docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..
```

**Why parent context?** The `..` allows access to `common/` utilities (julian.m, fortwrite.m) while the local `.dockerignore` file controls exactly what gets included from the parent directory.

**Build Process:**
1. **Stage 1 (builder):** Installs MATLAB R2024b + Compiler, compiles wrapper and dependencies
2. **Stage 2 (runtime):** Copies compiled executable to minimal MATLAB Runtime container

**Build time:** ~15-20 minutes (first build), ~2-3 minutes (cached)

### Run the Container

**Production-matching interface** (7 arguments matching `l2p2bic` signature):

```bash
docker run --rm \
  --shm-size=512M \
  -v /path/to/l2p_files:/data/input \
  -v /path/to/bic_output:/data/output \
  mur-l2p:latest \
  AMSR2R Global /data/input /data/output 2025 220 0
```

**Arguments (all required, positional):**

```
Position 1: sensor   - Sensor name (AMSR2R, AVMTBG, MODISA, MODIST, or AVMTAG)
Position 2: region   - Region name ('Global' - typically always Global)
Position 3: indir    - Input directory containing L2P NetCDF files (e.g., /data/input)
Position 4: bicdir   - Output directory for BIC files (e.g., /data/output)
Position 5: year     - 4-digit year (e.g., 2025)
Position 6: day      - Day of year (1-366)
Position 7: rewrite  - Rewrite flag: 0=skip existing files, 1=overwrite existing files
```

**Example with custom paths:**

```bash
docker run --rm \
  -v /local/l2p_downloads:/input \
  -v /local/bic_files:/output \
  mur-l2p:latest \
  MODISA Global /input /output 2025 220 1
```

**Note:** Container expects L2P files already present in `indir`. Downloads are handled separately in production (cron jobs), not by this container.

### Expected Input Directory Structure

The module expects L2P NetCDF files in the specified `indir`:

```
{indir}/
├── *.nc       (L2P NetCDF files)
├── *.nc.bz2   (compressed L2P files)
└── *.nc.gz    (gzip-compressed L2P files)
```

Example with `/data/input` as indir:
```
/data/input/
├── 20250808000000-REMSS-L2P_GHRSST-SSTsubskin-AMSR2-L2B_rt_r39715-v02.0-fv01.0.nc
├── 20250808001430-REMSS-L2P_GHRSST-SSTsubskin-AMSR2-L2B_rt_r39716-v02.0-fv01.0.nc
└── 20250808005500-JPL-L2P_GHRSST-SSTskin-MODIS_A-D-v02.0-fv01.0.nc
```

**Note:** The container looks for files directly in `indir` (not in subdirectories).

### Expected Output Directory Structure

The module produces compressed BIC files in the specified `bicdir`:

```
{bicdir}/
└── {region}_{sensor}_{year}_{day}.bic.gz
```

Example with `/data/output` as bicdir:
```
/data/output/
├── Global_AMSR2R_2025_220.bic.gz
├── Global_MODISA_2025_220.bic.gz
└── Global_MODIST_2025_220.bic.gz
```

## Data Download

**IMPORTANT:** This container does NOT handle downloads. Like production, downloads are handled separately.

### Production Architecture

In the operational MUR system:
1. **Cron jobs** download L2P files hourly using `podaac-data-subscriber` (Python tool)
2. **nrtMRVA.py** calls `l2p2bic()` to process already-downloaded files
3. Container matches step #2 - processing only

### Downloading L2P Files

Use `podaac-data-subscriber` on your host system or via a separate container:

```bash
# Install (requires Python on host)
pip install podaac-data-subscriber

# Download data for a specific date
podaac-data-subscriber \
  -c AMSR2-REMSS-L2P-v8.2 \
  -d /path/to/l2p_files \
  -sd 2025-08-08T00:00:00Z \
  -ed 2025-08-08T23:59:59Z

# Then process with container
docker run --rm \
  -v /path/to/l2p_files:/data/input \
  -v /path/to/bic_output:/data/output \
  mur-l2p:latest \
  AMSR2R Global /data/input /data/output 2025 220 0
```

### PO.DAAC Collections by Sensor

| Sensor | Collection ID |
|--------|---------------|
| AMSR2R | AMSR2-REMSS-L2P-v8.2 or AMSR2-REMSS-L2P_RT-v8.2 |
| AVMTBG | AVHRRMTB_G-NAVO-L2P-v2.0 |
| MODISA | MODIS_A-JPL-L2P-v2019.0 |
| MODIST | MODIS_T-JPL-L2P-v2019.0 |

### NASA Earthdata Authentication

Create a `.netrc` file for `podaac-data-subscriber`:

```bash
touch ~/.netrc
chmod 600 ~/.netrc

cat > ~/.netrc << 'EOF'
machine urs.earthdata.nasa.gov
    login your-username
    password your-password
EOF
```

**Get credentials:**
- Register: https://urs.earthdata.nasa.gov/
- Approve PO.DAAC: https://urs.earthdata.nasa.gov/approve_app?client_id=BO_n7nTIlMljdvU6kRRB3g

## Processing Modes

### Rewrite Flag

The `rewrite` argument (position 7) controls whether existing output files are overwritten:

- **rewrite=0**: Skip processing if output BIC file already exists (default for stable data)
- **rewrite=1**: Always process, overwrite existing BIC file (use for NRT reprocessing)

**Usage in production:**
- NRT processing uses `rewrite=1` within stability window (2-3 days depending on sensor)
- Historical processing uses `rewrite=0` to skip already-processed days

### Integration with MUR Workflow

In the MUR processing pipeline (see [PROCESSING_FLOW_REPORT.md](../../mur-internal/PROCESSING_FLOW_REPORT.md)):

1. **L2P Processing** (this module): Download and convert satellite data to BIC format
2. **IQUAM Processing**: Process in-situ buoy observations
3. **Land/Ice Processing**: Generate land/ice masks
4. **Input Generation**: Combine all sources into unified BIQ format
5. **MRVA Analysis**: Multi-scale variational analysis
6. **NetCDF Output**: Generate final MUR product

## Volume Mounts

| Mount Point | Type | Purpose | Size Estimate |
|-------------|------|---------|---------------|
| `/data/input` | Read-write | L2P NetCDF downloads | 1-5 GB/day |
| `/data/output` | Read-write | BIC output files | 50-500 MB/sensor/day |
| `/data/logs` | Read-write | Processing logs | < 10 MB |
| `/tmp/l2p_tmp` | Ephemeral | Decompression workspace | < 1 GB |

## Performance Considerations

### Resource Requirements

- **Memory:** 2-4 GB (depends on file count and size)
- **CPU:** Single-threaded (MATLAB compiled code)
- **Disk I/O:** Significant (decompression, NetCDF reading, binary writing)
- **Network:** Only if downloading (10-500 MB/sensor/day)

### Optimization Tips

1. **Pre-stage data** - Download L2P files outside container for better control
2. **Use SSD** - NetCDF reading is I/O intensive
3. **Increase shared memory** - Add `--shm-size=512M` to docker run
4. **Parallel processing** - Run multiple sensors in parallel (different containers)
5. **Batch by sensor** - Process all days for one sensor before switching

### Typical Runtime

- **AMSR2R** (microwave): 2-5 minutes (few large swaths)
- **MODISA/MODIST** (infrared): 10-30 minutes (many granules)
- **AVMTBG** (AVHRR): 5-15 minutes (moderate granule count)

## Sensor-Specific Notes

### AMSR2R (Microwave)

- **Two collections:** Standard (reprocessed) + RT (real-time)
- Wrapper checks both, prioritizes standard
- All-weather capability (cloud-transparent)
- Coarser spatial resolution (~25 km)
- Fewer files per day (~30-50 granules)

### MODIS Aqua/Terra (Infrared)

- High spatial resolution (~1 km)
- Cloud contamination (gaps in coverage)
- Many granules per day (200-300 files)
- Longer processing time due to file count
- Terra (MODIST) has 3-day stability vs 2-day for Aqua

### AVHRR MetOp-B (Infrared)

- Moderate resolution (~1-4 km)
- Heritage sensor (long data record)
- Similar characteristics to MODIS but fewer granules

## Configuration

### Sensor Parameters (in SensorTable.m)

The `SensorTable.m` function provides sensor-specific parameters for each supported sensor:

- **File name patterns** - For locating L2P files in input directory
- **Confidence thresholds** - Quality filtering criteria
- **Decompression commands** - bzip2/gzip handling
- **Subdirectory paths** - Data organization structure

### l2p_wrapper.m Validation

The wrapper validates all inputs before calling `l2p2bic()`:

- **Sensor name** - Must be one of: AMSR2R, AVMTBG, MODISA, MODIST, AVMTAG
- **Year** - Must be between 1900 and 2100
- **Day** - Must be between 1 and 366
- **Rewrite flag** - Must be 0 or 1
- **Directories** - Creates output directory if it doesn't exist

## Troubleshooting

### Build Issues

**Problem:** Compilation timeout after 10 minutes
**Solution:** Check MATLAB license server connectivity, increase timeout in Dockerfile

**Problem:** Missing MATLAB toolbox error during build
**Solution:** Verify MATLAB_Compiler is installed (stage 1 of Dockerfile)

### Runtime Issues

**Problem:** "No .nc files found" warning
**Solution:** Check input directory structure matches expected layout (SENSOR/DOY/*.nc)

**Problem:** "Expected output file not found"
**Solution:** Check logs in /data/logs, verify l2p2bic completed successfully

**Problem:** Out of memory error
**Solution:** Reduce file count (process fewer days), increase container memory limit

**Problem:** Slow performance
**Solution:** Use SSD storage, increase --shm-size, check for excessive decompression

## Comparison with Legacy Python Driver

| Aspect | Legacy (Python) | Current (Pure MATLAB) |
|--------|----------------|---------------------------|
| **Driver** | execute_l2p.py | l2p_wrapper.m (compiled) |
| **Interface** | Custom 6 args (named) | Production 7 args (l2p2bic signature) |
| **Arguments** | argparse (named) | Positional strings |
| **Dependencies** | Python + MATLAB | MATLAB Runtime only |
| **Image Size** | ~8 GB | ~2.5 GB |
| **Build Time** | 5 min | 15-20 min (first), 2-3 min (cached) |
| **Runtime** | Interpreted Python + MATLAB | Compiled MATLAB |
| **Config** | config.json (test only) | Not used (like production) |
| **Downloads** | Integrated option | Separate (like production) |
| **Template Script** | l2p_template.m generated | Direct l2p2bic() call |
| **Production Match** | ❌ Custom interface | ✅ Matches nrtMRVA.py |

## Integration with Other MUR Modules

All MUR processing modules follow a consistent containerization pattern:

| Module | Wrapper | Runtime | Build Pattern |
|--------|---------|---------|---------------|
| **iquam** | buoyDataProcessing.m | MATLAB Runtime | Compile → Runtime |
| **landice** | landice_wrapper.m | MATLAB Runtime | Compile → Runtime |
| **l2p** | l2p_wrapper.m | MATLAB Runtime | Compile → Runtime |

## Future Enhancements

1. **Parallel granule processing** - Use parfor for multiple NetCDF files
2. **Quality metrics** - Track observation counts, coverage statistics
3. **Automated retry** - Handle transient processing failures
4. **Multi-day processing** - Process date ranges in single container run

## References

### External Documentation

**PO.DAAC Data Access:**
- Portal: [https://podaac.jpl.nasa.gov/](https://podaac.jpl.nasa.gov/)
- Data Subscriber: [https://github.com/podaac/data-subscriber](https://github.com/podaac/data-subscriber)
- Earthdata Login: [https://urs.earthdata.nasa.gov/](https://urs.earthdata.nasa.gov/)

**GHRSST L2P Specification:**
- Format Guide: [https://www.ghrsst.org/ghrsst-data-services/products/](https://www.ghrsst.org/ghrsst-data-services/products/)
- Data Specification v2.0

**Sensor Information:**
- AMSR2: [https://suzaku.eorc.jaxa.jp/GCOM_W/](https://suzaku.eorc.jaxa.jp/GCOM_W/)
- MODIS: [https://modis.gsfc.nasa.gov/](https://modis.gsfc.nasa.gov/)
- AVHRR: [https://www.star.nesdis.noaa.gov/smcd/emb/avhrr/](https://www.star.nesdis.noaa.gov/smcd/emb/avhrr/)

### Citation

If using MUR SST data or this processing system in publications, please cite:

> Chin, T. M., J. Vazquez-Cuervo, and E. M. Armstrong (2017), A multi-scale high-resolution analysis of global sea surface temperature, *Remote Sensing of Environment*, 200, 154-169, doi:10.1016/j.rse.2017.07.029

## License

This software is part of the MUR SST processing system developed at NASA Jet Propulsion Laboratory.
