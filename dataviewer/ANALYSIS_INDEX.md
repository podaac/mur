# MUR Dataviewer - Complete Analysis Index

This directory contains comprehensive documentation of the MUR dataviewer implementation, including architectural analysis and detailed rendering strategy documentation.

## Documentation Files

### Primary Analysis Documents

1. **ARCHITECTURE.md** (22 KB)
   - Complete technical architecture overview
   - All 10 supported file formats with detailed specifications
   - Core module responsibilities and designs
   - CLI interface documentation
   - Scatter plot rendering strategy (3-tier system)
   - Matplotlib configuration and figure layouts
   - File information and statistics reporting
   - File comparison methodology
   - Large dataset handling strategies
   - Performance benchmarks
   - Security and robustness analysis
   - Code statistics and metrics

2. **SCATTER_RENDERING_STRATEGY.md** (22 KB)
   - Deep-dive into scatter plot rendering
   - Tier 1: Standard Matplotlib (≤100k points)
   - Tier 2: Value Aggregation (>100k with mpl-scatter-density)
   - Tier 3: Smart Downsampling (>100k without mpl-scatter-density)
   - Smart downsampling algorithm (outlier preservation)
   - Robust colorbar limits (MAD method)
   - Rendering decision flowchart
   - Performance comparison tables
   - Real-world example (50M MODIS observations)
   - Technical notes and rationale
   - Future enhancement possibilities

3. **README.md** (12 KB)
   - User-focused documentation
   - Features and supported formats
   - Installation instructions
   - Usage examples with command-line examples
   - Output statistics for each format
   - Plotting features and layouts
   - Resampling strategy
   - Troubleshooting guide
   - Architecture overview
   - Testing procedures
   - Performance benchmarks
   - Future enhancements roadmap

### Source Code Files

- **dataviewer.py** (~1,480 lines)
  - CLI application and main entry point
  - File information printing
  - Plotting logic for all formats
  - File comparison implementation
  - Data export functionality
  - Matplotlib backend negotiation

- **format_readers.py** (~765 lines)
  - 10 format reader classes
  - Auto format detection
  - Gzip decompression handling
  - Fortran binary parsing for each format
  - NetCDF reading via netCDF4

- **fortran_io.py** (~303 lines)
  - Fortran binary record reading
  - FortranReader class
  - MATLAB-compatible fortread() function
  - Record header/trailer validation

- **test_viewer.py** (~198 lines)
  - Test suite
  - Format detection tests
  - File reading tests
  - Fortran I/O tests

## Quick Reference

### Entry Point
```bash
mur-viewer [files] [--options]
```

### Core Features
- 10 supported file formats
- Automatic format detection
- 3-tier adaptive rendering for scatter plots
- Robust statistics (MAD-based)
- File comparison with tolerance
- Data export
- Gzip transparency

### Rendering Strategy
| Point Count | Method | Performance | Memory |
|-------------|--------|-------------|--------|
| ≤100k | Standard scatter | Good | ~2 MB/100k |
| 100k-10M+ | Value aggregation* | Excellent | ~2-3 MB |
| 100k+ | Smart downsampling** | Good | ~2 MB |

*Requires mpl-scatter-density
**Fallback if mpl-scatter-density not available

## File Format Guide

### Point Data Formats
- **BIP** - Ice SST point data (lon, lat, hour, sst, weight)
- **BIQ** - Unified observation format (same as BIP after QC)
- **BII** - In-situ buoy observations (platform metadata)
- **BIC** - Satellite L2P swath with bias and RMS error
- **BIN** - Legacy satellite format (older data)

### Grid Data Formats
- **GDS** - Gridded land/ice mask (36k×18k typical)
- **MAP** - Quick-look gridded SST output

### Coefficient Formats
- **CSP** - Multi-scale B-spline coefficients
- **USP** - Uncertainty coefficients

### Scientific Data Formats
- **NetCDF** - GHRSST L4 products (standard output)

## Statistical Methods

### Robust Statistics (MAD)
```
Colorbar limits computed as:
- vmin = median(data) - 3 * robust_std
- vmax = median(data) + 3 * robust_std
- robust_std = 1.4826 * median(|data - median|)

Advantages over min/max:
- Resistant to 25% outlier contamination
- Better contrast for oceanographic data
- Identifies extreme outliers (>4σ)
```

## Performance

### Reading Speeds (Uncompressed)
- BIP/BIQ (100k): ~0.1s
- GDS (36k×18k): ~2s
- BIC (1M): ~0.5s
- NetCDF (350MB): ~3s

### Rendering Times (with mpl-scatter-density)
- 100k points: ~0.5s
- 1M points: ~1s
- 10M points: ~2s

### Memory Usage
- Direct scatter (100k): ~2 MB
- Aggregated (10M): ~2-3 MB (constant!)
- Gzip decompression: 2-5× overhead

## Installation

### Basic Installation
```bash
cd /path/to/mur
uv pip install -e .
```

### Performance Optimization
```bash
pip install mpl-scatter-density  # For large datasets (>100k points)
```

### Optional Features
```bash
pip install cartopy             # For coastlines
pip install netCDF4             # For NetCDF files
```

## Common Commands

### View and Plot
```bash
mur-viewer data.gds
```

### Info Only (No Plot)
```bash
mur-viewer data.bip --info
```

### Compare Files
```bash
mur-viewer file1.bip file2.bip --compare
```

### Compare with Tolerance
```bash
mur-viewer file1.bip file2.bip --compare --tolerance 1e-4
```

### Export Data
```bash
mur-viewer data.biq --export output.txt
```

### Control Resampling
```bash
mur-viewer large.gds --resample 10
```

## Architecture Overview

```
dataviewer/
├── __init__.py              # Module exports
├── fortran_io.py            # Fortran binary I/O
│   ├── FortranReader class
│   └── fortread() function
├── format_readers.py        # Format-specific readers
│   ├── DataFileReader (base)
│   ├── BIPReader, GDSReader, BIIReader, ...
│   └── read_file() dispatcher
├── dataviewer.py            # Main application
│   ├── main() entry point
│   ├── plot_data() for visualization
│   ├── print_file_info() for statistics
│   ├── compare_files() for QC
│   └── CLI argument parsing
├── test_viewer.py           # Test suite
├── README.md                # User documentation
├── ARCHITECTURE.md          # Technical analysis [NEW]
├── SCATTER_RENDERING_STRATEGY.md  # Rendering details [NEW]
└── ANALYSIS_INDEX.md        # This file [NEW]
```

## Data Flow

```
User Input (CLI)
    ↓
[mur-viewer file.ext --options]
    ↓
Format Detection
    ↓
Read File (format-specific reader)
    ↓
Fortran I/O (if binary)
    ↓
Data Validation & Statistics
    ↓
Print Info
    ↓
Decide Rendering Strategy (if plotting)
    ↓
┌─────────┴─────────┬──────────────┬──────────────┐
├100k? Standard─────┼─────────────┤
└─────────┬─────────┴──────────────┴──────────────┘
         Plot & Display
              ↓
    [Interactive Matplotlib Window]
```

## Key Algorithms

### Smart Downsampling (Preserves Outliers)
1. Identify points >3σ from mean (outliers)
2. Keep ALL outliers
3. Random sample normal points to reach 100k total
4. Render combined dataset
Result: Representative sample with guaranteed extreme value visibility

### Robust Statistics (MAD Method)
1. Calculate median of data
2. Calculate median of absolute deviations from median
3. Convert to standard deviation equivalent (×1.4826)
4. Use robust_std for colorbar limits (±3σ)
Result: Better contrast resistant to outliers

## Testing

### Test Suite Location
```
/Users/jleach/Documents/Development/MUR/mur/dataviewer/test_viewer.py
```

### Test Coverage
- Format detection (9 formats)
- File reading (GDS, BIP from truth data)
- Fortran I/O (record reading)

### Running Tests
```bash
cd /path/to/dataviewer
python test_viewer.py
```

## Known Limitations

1. Little-endian byte order hardcoded
2. No map projections (cartopy optional)
3. Simple nearest-neighbor grid resampling
4. Tested primarily on Linux
5. No built-in zoom/pan (relies on matplotlib)

## Future Enhancements

- [ ] Map projection support (basemap/cartopy)
- [ ] NetCDF variable selection
- [ ] Time series animation
- [ ] Interactive GUI (Qt/Tk)
- [ ] Batch processing mode
- [ ] JSON/HDF5 export
- [ ] Difference visualization
- [ ] CSV statistics export
- [ ] Hexbin density plots
- [ ] GPU acceleration

## Security & Safety

### Security Features
- Static format detection (no code execution)
- File validation (record headers/trailers)
- No external command execution
- NumPy bounds checking (memory safety)

### Error Handling
- Graceful dependency fallbacks
- Try/except blocks for optional features
- Detailed error messages
- Temp file cleanup in exception handlers

## Integration Points

### MUR Pipeline
- Input: Binary files from processing pipeline
- Use case: QC validation after processing
- Output: Plots and exported statistics
- Comparison: Verify against reference files

### Data Locations
```
/nas2/landice/YYYY/              # Ice masks (reference)
/nas/ftp/.../landice/YYYY/       # Ice masks (0.01° resolution)
/nas2/iquam/YYYY/                # Buoy data (BII)
/nas2/bic/SENSOR/YYYY/           # Satellite data (BIC)
/nas4/cyc4out/YYYY/              # Coefficients (CSP/USP)
/nas/ftp/.../L4/.../             # Final products (NetCDF)
```

## Contact & Support

- Primary documentation: README.md
- Technical details: ARCHITECTURE.md
- Rendering details: SCATTER_RENDERING_STRATEGY.md
- Issues/questions: Refer to MUR processing documentation

---

**Last Updated:** 2025-12-04
**Documentation Version:** 1.0
**Dataviewer Version:** 1.0.0
