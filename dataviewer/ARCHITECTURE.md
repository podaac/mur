# MUR Dataviewer Implementation Analysis

## Executive Summary

The MUR dataviewer is a comprehensive Python visualization tool for browsing and analyzing SST (Sea Surface Temperature) processing data files. It supports 10+ binary formats and NetCDF files with intelligent rendering strategies optimized for datasets ranging from thousands to millions of points.

**Key Characteristics:**
- Location: `/Users/jleach/Documents/Development/MUR/mur/dataviewer/`
- Entry point: `mur-viewer` command (via `/mur/.venv/bin/mur-viewer`)
- 3 core modules: `fortran_io.py`, `format_readers.py`, `dataviewer.py`
- ~1,500 lines of code (main module)
- Supports 10 file formats with automatic detection
- 3-tier rendering strategy for scatter plots

---

## 1. Directory Structure

```
/Users/jleach/Documents/Development/MUR/mur/dataviewer/
├── __init__.py              # Module exports (v1.0.0)
├── __pycache__/             # Compiled Python modules
├── dataviewer.py            # Main CLI application (62.9 KB)
├── web_viewer.py            # Streamlit web interface
├── format_readers.py        # Format-specific readers (23.8 KB)
├── fortran_io.py            # Fortran binary I/O utils (8.9 KB)
├── sources.py               # Data-source catalogs (local / MAAP STAC / PO.DAAC)
├── viewer_config.py         # Data-source configuration resolution
├── test_viewer.py           # Test suite (5.8 KB)
└── README.md                # Documentation (12.1 KB)
```

### Data-source layer (`sources.py`, `viewer_config.py`)

Used by the web viewer only. It separates *what a granule is* from *where it
lives*, so that discovery and download stay out of the read/plot/diff path:

- **`Granule`** — an id, a date, a mode (`nrt`/`rea`) and an href that may be a
  local path, an `s3://` key or an `https://` URL.
- **`Catalog`** — `search(start, end)`, `find_for_date(day)` and
  `fetch(granule) -> Path`. Three implementations: `LocalCatalog`,
  `MaapStacCatalog` (MAAP STAC API, falling back to the deterministic item keys
  in the workspace bucket) and `PublicMurCatalog` (PO.DAAC via CMR/earthaccess).

Everything downstream — the format readers, `build_full_res_diff`, the plots —
keeps operating on local paths and never learns a file came from a catalogue.
That is deliberate: the diff opens both files with `netCDF4.Dataset` and reads
them in row chunks, so a lazy remote handle would have to satisfy the whole
HDF5 read path. Downloading once into a content-addressed cache is simpler and,
for a file read in thousands of chunks, faster.

`earthaccess`, `s3fs` and `requests` are imported *inside* the methods that need
them, so importing `dataviewer` — and running the local-only viewer — requires
none of them.

---

## 2. Supported File Formats

| Format | Extension | Description | Type | Notes |
|--------|-----------|-------------|------|-------|
| **BIP** | `.bip[.gz]` | Ice SST point data | Point | 5 fields per point |
| **GDS** | `.gds[.gz]` | Gridded land/ice mask | Grid | 36k×18k typical |
| **BII** | `.bii` | In-situ buoy observations | Point | Platform metadata |
| **BIC** | `.bic[.gz]` | Satellite L2P swath with bias | Point | Compressed int16 |
| **BIQ** | `.biq` | Unified observation format | Point | QC'd data |
| **BIN** | `.bin` | Legacy satellite format | Point | Historical data |
| **MAP** | `.map` | Quick-look gridded SST | Grid | Display output |
| **CSP** | `.c00`-`.c11` | Multi-scale coefficients | Array | B-spline basis |
| **USP** | `.u06`-`.u08` | Uncertainty coefficients | Array | Posterior variance |
| **NetCDF** | `.nc[4]` | GHRSST L4 products | Grid | MUR standard output |

**Compression Support:**
- All formats except `.bii` and `.bin` support optional `.gz` compression
- Automatic decompression via temp file handling

---

## 3. Core Module Architecture

### 3.1 `fortran_io.py` (Fortran Binary I/O)

**Responsibility:** Handle Fortran unformatted binary record structure

**Key Components:**

```python
class FortranReader:
    """Record-based Fortran binary file reader"""
    
    Methods:
    - read_record_header()      # Read 4-byte size header
    - read_record_trailer()     # Read 4-byte size trailer
    - read_int32(count)         # Read 32-bit integers
    - read_int16(count)         # Read 16-bit integers
    - read_int8(count)          # Read 8-bit integers
    - read_uint8(count)         # Read unsigned 8-bit
    - read_float32(count)       # Read 32-bit floats
    - read_record(*dtypes)      # Composite record reader
```

**Features:**
- Context manager support (`with` statement)
- Automatic record size validation
- Little-endian byte order (hardcoded)
- NumPy array output for bulk reads
- Scalar returns for single values

**Legacy Support:**
```python
def fortread(f, *args):
    """MATLAB-style fortread compatibility"""
    # Format: fortread(f, 'dtype', count, 'dtype', count, ...)
    # Examples:
    #   year, day, N = fortread(f, 'integer*4', 1, 'integer*4', 1, 'integer*4', 1)
    #   lon = fortread(f, 'real*4', N)
```

---

### 3.2 `format_readers.py` (Format Detection & Reading)

**Responsibility:** Format-specific data parsing

**Detection Logic:**
```python
detect_format(filepath) -> str
    # Case-insensitive filename matching:
    # - '.bip' → 'bip'
    # - '.gds' → 'gds'
    # - '.bii' → 'bii'
    # - '.bic' → 'bic'
    # - '.biq' → 'biq'
    # - '.bin' → 'bin'
    # - '.map' → 'map'
    # - '.cXX' (00-19) → 'csp'
    # - '.uXX' (00-19) → 'usp'
    # - '.nc', '.nc4' → 'nc'
    # Strips .gz automatically
```

**Reader Classes:**

#### BIPReader
```
Record 1: N (int32)
Record 2: 
  - lon[N] (float32)
  - lat[N] (float32)
  - hour[N] (float32)       # Time offset (0-24 hours)
  - sst[N] (float32)        # Degrees C
  - weight[N] (float32)     # Observation weight
```

#### GDSReader
```
Record 1: ii, jj (int32)    # Grid dimensions
Record 2:
  - mask[ii×jj] (int8)      # Land/ice/water classification
  - lon[ii] (float32)       # Column coordinates
  - lat[jj] (float32)       # Row coordinates
Record 3: icemap[ii×jj] (int8)  # Ice concentration (0-100%, -1 invalid)
```

**Key Detail:** Uses Fortran column-major order (order='F' in reshape)

#### BIIReader
```
Record 1: N, year, day (int16/int32 mixed)
Record 2: SST, lon, lat, hour, platform (int16 scaled data + int8)
  - Scaling: divide all by 100
  - SST: subtract 273.15 for Celsius conversion
  - Platform codes: 0-13 (buoys, ships, ice stations, etc.)
```

#### BICReader (Compressed Satellite)
```
Record 1: year, day, N (int32)
Record 2: offset, sst_scale, hour_scale (float32)
Record 3: Data arrays with mixed precision:
  - lon, lat (float32)
  - hour, sst, bias, rms (int16 compressed)
  - quality (uint8)
  - Unscaling: value = raw_int * scale + offset
```

#### BIQReader (Unified Format)
```
Same as BIP: lon, lat, hour, sst, weight (all float32)
```

#### BINReader (Legacy)
```
Record 1: year, day, N (int32)
Record 2: 8 arrays of float32:
  - lon, lat, sst, bias, rms, hour
  - confidence (int32)
  - sun_zenith indicator
```

#### MAPReader (Quick-Look Grid)
```
Record 1: nlon, nlat (int32)
Record 2: sst[nlon×nlat] (float32), lon[nlon], lat[nlat]
  - SST in Kelvin, converted to Celsius
  - Invalid: > 400K or == 999.0 → NaN
```

#### CSP/USPReader (Coefficients)
```
Record 1: mx, my, mz, nv (int32)      # 4D grid dimensions
Record 2: xmin, xmax, ymin, ymax (float32)  # Spatial bounds
Record 3: coefficients array (float32)
  - Size: (mx+3-cix) × (my+3) × mz × nv
  - cix = 3 (cyclic boundary condition)
  - Stored in Fortran order
```

#### NetCDFReader
```
Uses netCDF4 library
Extracts:
  - All variables with data, dimensions, attributes
  - Global attributes
  - Dimension names and sizes
```

---

### 3.3 `dataviewer.py` (Main Application)

**Responsibility:** CLI interface, plotting, statistics, comparison

**Entry Point:**
```bash
mur-viewer file1.ext [file2.ext] [OPTIONS]
```

---

## 4. Command-Line Interface

### Basic Syntax

```bash
mur-viewer file [file] [OPTIONS]
```

### Options

| Option | Type | Default | Purpose |
|--------|------|---------|---------|
| `--info` | flag | False | Show file info only (no plot) |
| `--compare` | flag | False | Compare two files (requires exactly 2) |
| `--export FILE` | path | None | Export data to text |
| `--resample N` | int | auto | Resampling factor for grids |
| `--tolerance TOL` | float | 1e-6 | Numerical tolerance for comparisons |

### Usage Examples

```bash
# Default: view and plot
mur-viewer data.gds

# Info only
mur-viewer data.bip --info

# Compare files
mur-viewer file1.bip file2.bip --compare

# Compare with custom tolerance
mur-viewer file1.bip file2.bip --compare --tolerance 1e-4

# Export to CSV
mur-viewer data.biq --export output.txt

# Control resampling
mur-viewer large.gds --resample 10
```

---

## 5. Scatter Plot Rendering Strategy

### Intelligent 3-Tier Performance System

The viewer implements **adaptive rendering** based on point count:

```
POINT COUNT DECISION TREE
│
├─ N ≤ 100,000
│  └─> STANDARD MATPLOTLIB SCATTER
│      • Direct scatter plot
│      • 1 point = 1 marker
│      • Fast rendering
│      • Memory: ~400MB per 1M points
│
├─ 100k < N ≤ 10M (with mpl-scatter-density installed)
│  └─> VALUE AGGREGATION RENDERING
│      • Group points into pixels
│      • Show MEAN values (not just density)
│      • Interactive zoom/pan
│      • ~2 seconds for 10M points
│
└─ 100k < N (without mpl-scatter-density)
   └─> SMART DOWNSAMPLING
       • Preserve all outliers (>3σ)
       • Random sample from normal distribution
       • Max 100k plotted points
       • Maintains spatial patterns
```

### Implementation Details

**Detection Threshold:**
```python
DENSITY_THRESHOLD = 100000

if num_points > DENSITY_THRESHOLD:
    try:
        import mpl_scatter_density
        use_density = True
    except ImportError:
        use_downsampling = True
```

**Smart Downsampling Algorithm:**
```python
def smart_downsample(x, y, c=None, max_points=100000):
    """
    1. Identify outliers: |value - mean| > 3*std
    2. Keep ALL outliers
    3. Randomly sample normal points to fill remaining quota
    4. Concatenate outliers + sample
    """
    outlier_mask = (abs(x - mean_x) > 3*std_x) | (abs(y - mean_y) > 3*std_y)
    outliers_x = x[outlier_mask]
    normal_x = x[~outlier_mask]
    
    n_sample = max_points - len(outliers_x)
    indices = np.random.choice(len(normal_x), n_sample, replace=False)
    sampled = normal_x[indices]
    
    return np.concatenate([outliers_x, sampled])
```

**Robust Colorbar Limits:**
```python
def compute_robust_stats(data):
    """Median Absolute Deviation (MAD) method"""
    median = np.median(data)
    mad = np.median(abs(data - median))
    robust_std = 1.4826 * mad  # Scaling factor for normality
    
    # Colorbar: median ± 3*robust_std
    vmin = median - 3*robust_std
    vmax = median + 3*robust_std
    
    # Count outliers beyond 4σ
    outlier_mask = abs(data - median) > 4*robust_std
    n_outliers = sum(outlier_mask)
    pct_outliers = 100.0 * n_outliers / len(data)
```

---

## 6. Matplotlib Configuration & Plotting

### Backend Selection

```python
import matplotlib
import matplotlib.pyplot as plt

# Automatic backend negotiation:
current = matplotlib.get_backend()
if current.lower() == 'agg':  # Non-interactive
    try:
        matplotlib.use('TkAgg')  # Try Tk first
    except ImportError:
        try:
            matplotlib.use('Qt5Agg')  # Fallback to Qt5
        except ImportError:
            print("⚠️ Using non-interactive backend")
```

### Figure Layouts

#### Point Data (BIP, BIQ, BIC, BIN)

**With mpl-scatter-density (>100k points):**
```
┌─────────────────────────┐
│ Subplot 1: SST Density  │ Subplot 2: SST Histogram
│ scatter_density plot    │ (standard histogram)
│ c=sst_plot              │ All points included
│ cmap='RdYlBu_r'         │
├─────────────────────────┤
│ Subplot 3: Coverage     │ Subplot 4: Weight/RMS
│ Point density (white→   │ Aggregated values
│ yellow viridis)         │ scatter_density
└─────────────────────────┘
```

**Without mpl-scatter-density (<100k points):**
```
Standard 4 panel (scatter plot in each spatial subplot)
```

**BII Special Layout (Buoy Data):**
```
┌─────────────────────────┐
│ Top-left: SST Map       │ Top-right: Platform Type
│ scatter or density      │ scatter (categorical colors)
├─────────────────────────┤
│         Histogram (full width)      │
└─────────────────────────┘
```

#### Grid Data (GDS)

```
┌──────────────────┬──────────────────┐
│ Left: Land/Ice   │ Right: Ice %      │
│ Mask categorical │ Blue gradient     │
│ (discrete colors)│ (-1 to 100%)      │
└──────────────────┴──────────────────┘
Shared axes for synchronized zoom
```

#### Coefficient Data (CSP/USP)

```
┌──────────────────┬──────────────────┐
│ Left: 2D Slice   │ Right: Histogram │
│ Through 4D array │ (log scale)      │
│ cmap='RdBu_r'    │ All coefficients │
└──────────────────┴──────────────────┘
```

### Color Mapping

| Data Type | Colormap | Range | Notes |
|-----------|----------|-------|-------|
| SST | `RdYlBu_r` | median±3σ | Robust statistics |
| Weight | `viridis` | auto | Sequential |
| RMS | `hot_r` | auto | Reverse heat |
| Density | Custom white_viridis | 0-max | White background |
| Mask | `tab10` discrete | per-value | Categorical |
| Coefficients | `RdBu_r` | auto | Diverging |

### Special Features

**Coastlines (Optional):**
```python
# Requires: cartopy
add_coastlines(ax)
    # Uses Natural Earth 110m resolution
    # Plots LineString/MultiLineString geometries
    # Black lines with alpha=0.5
```

**Help Box (Information Panel):**
```
Rendered at bottom-left of figure:
- Total points / grid size
- Rendering mode (scatter/density/downsampled)
- What each panel shows
- Installation tips for optimization
- Matplotlib backend info
```

---

## 7. File Information & Statistics

### Point Data Statistics (BIP, BIQ, BII, BIC, BIN)

```
Number of points: N
Longitude range: [lon_min, lon_max]
Latitude range: [lat_min, lat_max]
SST range: [sst_min, sst_max] °C
SST mean: μ
SST std: σ

Robust Statistics (MAD-based):
  SST median: m
  SST robust std: σ_robust
  Outliers (>4σ): count (%)

Format-specific:
  BIP/BIQ: hour range, weight range
  BII: year, day, platform type breakdown
  BIC: bias range, RMS range, quality values
  BIN: confidence levels, sun zenith
```

### Grid Data Statistics (GDS)

```
Grid dimensions: ii × jj = total_pixels
Longitude range: [-180, 180]
Latitude range: [-90, 90]

Mask values distribution:
  1 (open sea): count (%)
  2 (land): count (%)
  5 (lakes): count (%)
  9 (sea+ice): count (%)
  13 (lakes+ice): count (%)

Ice concentration:
  Range: [min, max]%
  Pixels with ice: count (%)
```

### Coefficient Statistics (CSP/USP)

```
Scale level: L=N
Grid dimensions: mx, my, mz, nv
Total coefficients: mx×my×mz×nv
Spatial bounds: [xmin, xmax] × [ymin, ymax]

Coefficient stats:
  Min: value
  Max: value
  Mean: value
  Std: value
```

---

## 8. File Comparison

**Command:**
```bash
mur-viewer file1.ext file2.ext --compare [--tolerance TOL]
```

**Comparison Logic:**

For **point data** (BIP, BIQ):
- Compare N (number of points)
- Array comparisons: `np.allclose(arr1, arr2, atol=tolerance, rtol=tolerance)`
- Report max difference and mismatches

For **grid data** (GDS):
- Compare dimensions
- Compare arrays with tolerance
- Report number and percentage of different elements

**Output:**
```
✅ Number of points match: 1,234,567
✅ lon matches
❌ sst differs (max diff: 0.0234)
❌ Some differences found
```

---

## 9. Data Export

**Format:** CSV-like text output

```
# Header:
# MUR Data Export
# File: /path/to/file
# Format: BIQ
# 
# Column headers
# lon, lat, sst[, hour, weight, bias, rms]
```

**Supported formats:** BIP, BIQ, BII, BIC, BIN (point data only)

---

## 10. Large Dataset Handling

### Memory Considerations

**Typical memory usage** (uncompressed):
```
100k points: ~2 MB
1M points: ~20 MB
10M points: ~200 MB
Matplotlib figure: ~50-100 MB
Total overhead: +100 MB (colormaps, rendering)
```

**gzip Decompression:**
```
Peak memory: ~2-5× the uncompressed size
Strategy: Decompress to temp file, read, delete
Temp location: system temp directory
```

### Grid Resampling

**Automatic for large grids:**
```python
max_display_size = 5000

if max(ii, jj) > max_display_size:
    resample_factor = ceil(max(ii, jj) / max_display_size)
    # e.g., 36000×18000 grid → 1800×900 display (factor=20)
    display = full[::resample_factor, ::resample_factor]
```

**Statistics:** Computed on full resolution, only display resampled

---

## 11. Error Handling

### Validation Checks

**File Format Detection:**
- Case-insensitive matching
- Handles compressed extensions
- Raises `ValueError` for unknown formats

**Record Structure:**
- Validates header == trailer (Fortran record wrapping)
- Checks expected record size
- Raises `ValueError` on mismatch

**Data Validity:**
- Filters lat/lon to [-90,90] and [-180,180]
- Checks for all-NaN grids
- Handles missing optional fields

**Import Availability:**
- Graceful fallback if matplotlib unavailable
- Cartopy optional (coastlines)
- netCDF4 optional (NetCDF files)
- mpl-scatter-density optional (performance)

---

## 12. Testing

**Test Suite:** `test_viewer.py`

```python
test_format_detection()     # 9 format strings
test_read_sample_files()    # GDS, BIP from test data
test_fortran_io()           # Record reading
```

**Test Data Location:**
```
/Users/jleach/Documents/Development/MUR/mur/landice/tests/truth-data/
```

---

## 13. Performance Benchmarks

**Reading speeds (uncompressed):**
```
BIP/BIQ (100k points): ~0.1s
GDS (36k×18k grid): ~2s
BIC (1M points): ~0.5s
CSP coefficient files: ~1s
NetCDF (350MB): ~3s
```

**Gzip overhead:** 2-5× slower

**Rendering times (with mpl-scatter-density):**
```
100k points: ~0.5s
1M points: ~1s
10M points: ~2s
```

**Without mpl-scatter-density (downsampling):**
```
100k points: ~1s
>100k points: ~2-3s (includes downsampling)
```

---

## 14. Dependencies

### Required
- `numpy` - Array operations
- `matplotlib` - Plotting
- `pathlib` - Path handling

### Optional
- `mpl-scatter-density` - Value aggregation rendering (recommended for >100k points)
- `cartopy` - Coastline drawing
- `netCDF4` - NetCDF file reading

### Installation

```bash
# From mur/ directory
uv pip install -e .  # Installs entry point + dependencies

# Additional performance
pip install mpl-scatter-density  # For large datasets
pip install cartopy              # For coastlines
pip install netCDF4              # For NetCDF files
```

---

## 15. Current Limitations & Potential Improvements

### Known Limitations

1. **Single Backend:** No map projections (requires basemap/cartopy integration)
2. **Fortran Byte Order:** Hardcoded little-endian (may not work on big-endian systems)
3. **Grid Resampling:** Uses simple nearest-neighbor (no max/min aggregation)
4. **Platform Compatibility:** Tested primarily on Linux
5. **Interactive Features:** No built-in zoom/pan controls (relies on matplotlib)

### Potential Enhancements (from README)

- [ ] Map projection support (basemap/cartopy)
- [ ] NetCDF variable plotting
- [ ] Time series animation
- [ ] Interactive GUI (Qt/Tk)
- [ ] Batch processing mode
- [ ] JSON/HDF5 export
- [ ] Difference visualization
- [ ] Statistics export to CSV

---

## 16. Key Code Patterns

### Pattern 1: Robust Statistics

```python
# Using Median Absolute Deviation instead of std
median = np.median(data)
mad = np.median(np.abs(data - median))
robust_std = 1.4826 * mad

# Colorbar limits: median ± 3*robust_std
# Count outliers beyond 4*robust_std
```

**Advantage:** Resistant to extreme outliers (e.g., -1.8°C ice points in warm water)

### Pattern 2: Adaptive Rendering

```python
if num_points > 100k:
    if has_mpl_scatter_density:
        use_density = True
    else:
        use_downsampling = True
        num_points = downsample(lon, lat, sst)
```

### Pattern 3: Composite Plotting

```python
# Share axes for linked zoom/pan
ax1 = fig.add_subplot(2, 2, 1)
ax3 = fig.add_subplot(2, 2, 3, sharex=ax1, sharey=ax1)

# Creates synchronized views of same region
```

### Pattern 4: Gzip Transparency

```python
# Auto-detect and handle compression
if filepath.suffix == '.gz':
    with gzip.open(filepath) as gz:
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(gz.read())  # Decompress
            result = read_data(tmp.name)  # Read uncompressed
```

---

## 17. Integration with MUR Pipeline

**Data Locations:**
```
/nas2/landice/YYYY/              # Ice masks (reference)
/nas/ftp/.../landice/YYYY/       # Ice masks (0.01° resolution)
/nas2/iquam/YYYY/                # Buoy data (BII)
/nas2/bic/SENSOR/YYYY/           # Satellite data (BIC)
/nas4/cyc4out/YYYY/              # Coefficients (CSP/USP)
/nas/ftp/.../L4/.../             # Final products (NetCDF)
```

**Typical Workflow:**
```
1. Run processing pipeline → binary output files
2. Use dataviewer for QC/validation
3. Compare with reference files
4. Export statistics for analysis
5. Visualize final NetCDF products
```

---

## 18. Code Statistics

| Metric | Value |
|--------|-------|
| Total Lines (all modules) | ~2,000 |
| Main module (dataviewer.py) | ~1,480 |
| Format readers (format_readers.py) | ~765 |
| Fortran I/O (fortran_io.py) | ~303 |
| Classes | 12 (1 base + 10 readers + 1 helper) |
| Functions | 20+ |
| Test coverage | Basic (format detection, file I/O) |
| Documentation | Comprehensive (README + docstrings) |

---

## 19. Security & Robustness

### Security Considerations

1. **File Validation:**
   - Format detection from filename (safe)
   - Record header/trailer validation
   - Bounds checking on arrays

2. **Memory Safety:**
   - NumPy array bounds checking
   - No buffer overflows (Python management)
   - Temp file cleanup in exception handlers

3. **No Arbitrary Code Execution:**
   - Static format detection
   - No script evaluation
   - No external command execution

### Error Recovery

- Try/except blocks for missing dependencies
- Graceful fallbacks (e.g., without cartopy, without mpl-scatter-density)
- Detailed error messages for troubleshooting

---

## 20. Scatter Plot Handling of Large Datasets

### Summary Table

| Aspect | Standard (<100k) | Value Aggregation (100k-10M+) | Downsampled (100k+, no density) |
|--------|------------------|------------------------------|--------------------------------|
| **Rendering Method** | Individual markers | Pixel averages | Random sample |
| **Points Shown** | All | Binned to grid | 100k selected |
| **Color Meaning** | Individual value | Mean value in pixel | Individual value |
| **Outlier Handling** | All preserved | Aggregated | All outliers kept |
| **Interactivity** | Pan/zoom slow | Pan/zoom fast | Pan/zoom fast |
| **Memory** | High | Low | Medium |
| **Installation** | matplotlib only | mpl-scatter-density | matplotlib only |
| **Render Time (10M)** | N/A | ~2 seconds | ~2 seconds |

---

## Conclusion

The MUR dataviewer is a well-engineered tool with:

✅ **Comprehensive format support** (10 binary + NetCDF)
✅ **Intelligent performance optimization** (3-tier rendering)
✅ **Robust statistics** (MAD-based outlier handling)
✅ **Production-grade error handling** (validation, fallbacks)
✅ **Complete documentation** (README + docstrings)
✅ **Easy CLI interface** (single entry point)
✅ **Quality assurance** (test suite, comparison tools)

**Primary Strength:** Automatic optimization for large datasets with 100k+ points
**Primary Use Case:** Interactive exploration and QC of MUR processing pipeline outputs
