# MUR Data Viewer

A Python utility for browsing and visualizing MUR (Multi-scale Ultra-high Resolution) SST processing data files.

## Features

- **Auto-detect** file formats from filename extensions
- **Read** various binary formats used in MUR processing pipeline
- **Visualize** data using matplotlib with automatic resampling for large grids
- **Compare** two files of the same format
- **Export** data to text format
- **Comprehensive statistics** for each file type

## Supported Formats

| Format | Extension | Description | Size |
|--------|-----------|-------------|------|
| BIP | `.bip` | Ice SST point data | Variable |
| GDS | `.gds` | Gridded land/ice mask | ~36k × ~18k |
| BII | `.bii` | In-situ buoy observations | Variable |
| BIC | `.bic` | Satellite L2P swath with bias/error | Variable |
| BIQ | `.biq` | Unified observation format (QC'd) | Variable |
| BIN | `.bin` | Legacy satellite format | Variable |
| CSP | `.c02`-`.c11` | Multi-scale coefficient files | Variable |
| USP | `.u06`-`.u08` | Uncertainty coefficient files | Variable |
| NetCDF | `.nc`, `.nc4` | GHRSST NetCDF4 output | ~350 MB |

All formats support gzip compression (`.gz` suffix).

## Installation

### Requirements

- Python 3.10+
- numpy
- matplotlib (for plotting)
- mpl-scatter-density (for efficient large dataset rendering)
- netCDF4 (optional, for NetCDF files)

### Install dependencies

```bash
# Using uv (recommended)
cd mur
uv pip install -e .

# Or using pip directly
pip install -e .
```

This includes optimized visualization support for large datasets (10M+ points).

### Performance Notes

For datasets with **>100,000 points**, the viewer automatically uses **value aggregation** with `mpl-scatter-density`:

- Shows **mean values** (SST, weight, RMS) aggregated into pixels, not just point density
- Handles 10M+ points with interactive performance (<2 second rendering)
- Fast zoom/pan operations
- Clear visualization of spatial value patterns
- Automatic resolution adjustment during interaction

If `mpl-scatter-density` is not available, it falls back to smart downsampling (100k points while preserving outliers).

## Usage

### Basic Usage

View and plot (default behavior):
```bash
mur-viewer data.gds
```

View file information only (no plot):
```bash
mur-viewer data.bip --info
```

### Compare Files

Compare two files of the same format:
```bash
mur-viewer file1.bip file2.bip --compare
```

With custom tolerance:
```bash
mur-viewer file1.bip file2.bip --compare --tolerance 1e-4
```

### Export Data

Export to text format (CSV-like):
```bash
mur-viewer data.biq --export output.txt
```

### Advanced Options

Control resampling for large grids:
```bash
# Auto-resample for display (default: max 5000 pixels)
mur-viewer landice_2025_199.gds.gz

# Force specific resampling factor
mur-viewer landice_2025_199.gds.gz --resample 10
```

## Examples

### Example 1: Ice/Land Mask File

```bash
mur-viewer /nas/ftp/mur_sst/tmchin/landice/2025/landice_2025_199.gds.gz
```

Output:
```
================================================================================
File: landice_2025_199.gds.gz
Format: GDS
Path: /nas/ftp/mur_sst/tmchin/landice/2025/landice_2025_199.gds.gz
================================================================================

Grid dimensions: 36000 × 17999 = 647,964,000 points

Longitude range: [-180.0000, 180.0000]
Latitude range:  [-89.9950, 89.9950]

Mask values: [1 2 5 9 13]
  1: 431,853,127 points (66.64%)
  2: 176,493,456 points (27.23%)
  5: 3,245,678 points (0.50%)
  9: 28,456,123 points (4.39%)
  13: 7,915,616 points (1.22%)

Ice concentration range: [30, 100]%
Pixels with ice: 36,371,739 (5.61%)
```

### Example 2: Satellite Data (BIC)

```bash
mur-viewer /nas2/bic/MODISA/2025/Global_MODISA_2025_199.bic.gz
```

Shows:
- Number of observations
- Geographic coverage
- SST statistics
- Bias/RMS distributions
- Quality flag breakdown

### Example 3: Coefficient Files

```bash
mur-viewer /nas4/cyc4out/2025/2025071809_MRVA4_Global.c10
```

Shows:
- Scale level (L=10)
- Grid dimensions
- Coefficient array shape
- Spatial bounds
- Statistical summary

### Example 4: Buoy Data

```bash
mur-viewer /nas2/iquam/2025/Global_IQUAM0_2025_199.bii
```

Shows:
- Year and day of year
- Number of observations
- SST statistics
- Platform type breakdown

## Output Statistics

### Point Data (BIP, BIQ, BII, BIC, BIN)

- Number of observations
- Longitude/latitude ranges
- SST range, mean, standard deviation
- Weight/RMS/bias distributions
- Quality flag or platform type breakdown

### Grid Data (GDS)

- Grid dimensions
- Longitude/latitude ranges
- Mask value distribution with percentages
- Ice concentration statistics
- Geographic extent

### Coefficient Files (CSP, USP)

- Scale level
- Grid dimensions and array shape
- Spatial bounds
- Coefficient statistics (min, max, mean, std)

### NetCDF Files

- Dimension sizes
- Variable list with shapes and types
- Global attributes

## Plotting Features

### Automatic Performance Optimization

The viewer automatically detects large datasets and chooses the optimal rendering strategy:

| Point Count | Rendering Method | Performance | Installation |
|-------------|------------------|-------------|--------------|
| < 100k | Standard matplotlib scatter | Fast | matplotlib only |
| > 100k (with mpl-scatter-density) | Value aggregation (mean) | Very fast (~2s for 10M points) | `pip install mpl-scatter-density` |
| > 100k (without) | Smart downsampling to 100k | Fast | matplotlib only |

**Value aggregation** creates a grid showing mean values in each pixel, enabling:

- Visualization of actual data values (SST, weight, RMS) not just point counts
- Interactive visualization of 10M+ points
- Fast zoom/pan operations
- Clear spatial patterns in the data
- Automatic resolution adjustment during interaction

**Smart downsampling** preserves data quality by:

- Keeping all statistical outliers (>3σ from mean)
- Randomly sampling from normal distribution
- Maintaining spatial distribution characteristics

### Point Data Plots (BIP, BIQ, BII, BIC, BIN)

Four-panel layout:

1. **SST map** - mean SST values aggregated into pixels (for large datasets) or individual points (small datasets)
2. **SST histogram** - distribution of all values (always full resolution)
3. **Geographic coverage** - point density showing observation concentration
4. **Additional field** - mean weights/RMS values (for large datasets) or individual points

**Features**:

- Color bars showing actual data values (°C, weights, RMS) or point density
- Interactive help box (bottom-left) explaining rendering mode and what plots show
- Automatic mode detection (scatter/value aggregation/downsampled) with explanation

### Grid Data Plots (GDS)

Two-panel layout:
1. **Land/ice mask** - categorical colormap
2. **Ice concentration** - blue gradient (0-100%)

Features:
- **Automatic resampling** for large grids (>2000 pixels)
- **Linked axes** for synchronized zooming/panning
- **Quality preservation** using max/min downsampling

### Coefficient Plots (CSP, USP)

Two-panel layout:
1. **2D slice** through coefficient array
2. **Histogram** of coefficient distribution (log scale)

## File Format Details

### BIP Format
```
Record 1: N (int32)
Record 2: lon(N), lat(N), hour(N), sst(N), weight(N) [float32 arrays]
```

### GDS Format
```
Record 1: ii, jj (int32) - dimensions
Record 2: mask(ii×jj) [int8], lon(ii) [float32], lat(jj) [float32]
Record 3: icemap(ii×jj) [int8]
```

### BIC Format
```
Record 1: year, day, N (int32)
Record 2: offset, sst_scale, hour_scale (float32)
Record 3: lon(N), lat(N) [float32], hour(N), sst(N), bias(N) [int16],
         rms(N), quality(N) [uint8]
```

### BIQ Format
```
Record 1: N (int32)
Record 2: lon(N), lat(N), hour(N), sst(N), weight(N) [float32 arrays]
```

### CSP/USP Format
```
Record 1: mx, my, mz, nv (int32)
Record 2: xmin, xmax, ymin, ymax (float32)
Record 3: coefficients((mx+3)×(my+3)×mz×nv) [float32 array]
```

All formats use **Fortran unformatted binary** with 4-byte record headers/trailers.

## Integration with MUR Pipeline

This viewer integrates with the MUR processing pipeline described in:
- [PROCESSING_FLOW_REPORT.md](../../mur-internal/PROCESSING_FLOW_REPORT.md)
- [MRVA_ALGORITHM_ANALYSIS.md](../../mur-internal/MRVA_ALGORITHM_ANALYSIS.md)

Common data locations:
```
/nas2/landice/YYYY/          # Ice masks (0.1° resolution)
/nas/ftp/.../landice/YYYY/   # Ice masks (0.01° resolution)
/nas2/iquam/YYYY/            # Buoy data
/nas2/bic/SENSOR/YYYY/       # Satellite data
/nas4/cyc4out/YYYY/          # Coefficient files
/nas/ftp/.../L4/.../         # Final NetCDF products
```

## Comparison with MATLAB Code

This viewer provides similar functionality to MATLAB readers:
- `readbip.m` → `BIPReader`
- `readgds.m` → `GDSReader`
- `readbii.m` → `BIIReader`
- `readbic.m` → `BICReader`
- `readbiq.m` → `BIQReader`

Key differences:
- **No temporary files** for gzip decompression in memory
- **Automatic format detection**
- **Built-in visualization**
- **Comparison utilities**
- **Cross-platform** (no MATLAB license required)

## Resampling Strategy

For large grids (>2000 pixels in any dimension), the viewer automatically resamples for display:

1. **Calculate resampling factor**: `factor = ceil(max(width, height) / 2000)`
2. **Index-based resampling**: `display = full[::factor, ::factor]`
3. **Max/min preservation** for difference visualization
4. **Statistics computed on full resolution** data

Example: 36000×18000 grid → 1800×900 display (20× resampling)

## Troubleshooting

### Import Error: No module named 'netCDF4'

```bash
pip install netCDF4
```

### Import Error: No module named 'matplotlib'

```bash
pip install matplotlib
```

### ValueError: Unknown file format

Check file extension matches one of the supported formats. For compressed files, use `.gz` suffix.

### Memory Error on Large Files

Use resampling for visualization:
```bash
./dataviewer.py large_file.gds.gz --plot --resample 50
```

### Fortran Record Size Mismatch

File may be corrupted or have different endianness. Try:
1. Check file integrity
2. Verify file is not truncated
3. Check if file was created on different architecture

## Architecture

```
dataviewer/
├── fortran_io.py        # Low-level Fortran binary I/O
├── format_readers.py    # Format-specific readers
├── dataviewer.py        # Main CLI application
└── README.md           # This file
```

### Module Responsibilities

**fortran_io.py**:
- `FortranReader` class for record-based reading
- `fortread()` function for MATLAB-style compatibility
- Handles headers, trailers, and record validation

**format_readers.py**:
- Format detection from filenames
- Individual reader classes for each format
- Unified `read_file()` interface
- Automatic gzip handling

**dataviewer.py**:
- Command-line interface
- Statistics reporting
- Matplotlib visualization
- File comparison
- Data export

## Testing

Test with sample files from MUR processing:

```bash
# Test ice data (plots by default)
mur-viewer ../landice/tests/truth-data/land/p011/2025/landice_2025_199.gds.gz

# Compare processing outputs
mur-viewer \
    ../landice/tests/truth-data/land/p011/2025/landice_2025_199.gds.gz \
    ../landice/tests/out/land/p011/2025/landice_2025_199.gds.gz \
    --compare

# View info only (no plot)
mur-viewer ../landice/tests/truth-data/land/p011/2025/landice_2025_199.gds.gz --info
```

## Performance

Typical reading speeds (uncompressed):
- BIP/BIQ (100k points): ~0.1s
- GDS (36k×18k grid): ~2s
- BIC (1M points): ~0.5s
- CSP coefficient files: ~1s
- NetCDF (350MB): ~3s

Gzip decompression adds ~2-5× overhead.

## Future Enhancements

- [ ] Map projection support (basemap/cartopy)
- [ ] NetCDF variable plotting
- [ ] Time series animation
- [ ] Interactive GUI (Qt/Tk)
- [ ] Batch processing mode
- [ ] JSON/HDF5 export
- [ ] Difference visualization
- [ ] Statistics export to CSV

## License

Part of the MUR SST processing system.

## Contact

For issues or questions, refer to the MUR processing documentation in `mur-internal/`.
