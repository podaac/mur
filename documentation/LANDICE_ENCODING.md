# Land/Ice Mask Encoding Reference

## Introduction

The MUR SST land/ice mask uses **bitwise flag encoding** to compactly represent multiple surface properties in a single `int8` value. This document explains the encoding scheme, mask values, processing pipeline, and usage examples.

## Table of Contents

1. [Bit Flag Structure](#bit-flag-structure)
2. [Mask Values](#mask-values)
3. [Processing Pipeline](#processing-pipeline)
4. [Usage Examples](#usage-examples)
5. [Data Validation](#data-validation)
6. [File Formats](#file-formats)

## Bit Flag Structure

### Flag Bits Definition

| Bit Position | Mask Value | Flag Name | Meaning |
|--------------|------------|-----------|---------|
| **Bit 0** | `1` (`0001b`) | `open_sea` | Pixel contains ocean water |
| **Bit 1** | `2` (`0010b`) | `land` | Pixel contains land |
| **Bit 2** | `4` (`0100b`) | `open_lake` | Pixel contains lake water |
| **Bit 3** | `8` (`1000b`) | `ice_in_grid` | Pixel contains ice (concentration > 0%) |
| **Bit 4** | `16` (`10000b`) | *(reserved)* | Currently unused |

### Bitwise Testing

**Python/NumPy:**
```python
import numpy as np

# Test if pixel has ice
has_ice = (mask & 8) != 0

# Test if pixel is land
is_land = (mask & 2) != 0

# Test if pixel is ocean (not land)
is_ocean = (mask & 2) == 0

# Test if pixel is lake
is_lake = (mask & 4) != 0

# Test if pixel is ice-covered ocean
ice_ocean = ((mask & 8) != 0) & ((mask & 1) != 0)
# OR simply: ice_ocean = (mask == 9)
```

**MATLAB:**
```matlab
% Test if pixel has ice
has_ice = bitand(mask, 8) ~= 0;

% Test if pixel is land
is_land = bitand(mask, 2) ~= 0;

% Test if pixel is ocean
is_ocean = bitand(mask, 2) == 0;

% Test if pixel is ice-covered ocean
ice_ocean = (mask == 9);
```

## Mask Values

### Base Mask Values (Static Classification)

These values are defined in static land mask files:
- `maskGLOBp01deg.gds` (0.01° resolution, ~1km)
- `maskGlob1km.gds` (1km resolution)

| Value | Binary | Bits Set | Description | Source |
|-------|--------|----------|-------------|--------|
| **1** | `0001b` | 0 | **Open sea** - Ocean water | Base mask |
| **2** | `0010b` | 1 | **Land** - Solid land | Base mask |
| **3** | `0011b` | 0+1 | **Coast/shore** - Land-ocean boundary | Base mask |
| **4** | `0100b` | 2 | **Lake boundary** - Lake edge marker | Base mask |
| **5** | `0101b` | 0+2 | **Open lake** - Lake water (e.g., Great Lakes) | Base mask |
| **7** | `0111b` | 0+1+2 | **Lake shore** - Lake-land boundary | Base mask |

**Note:** Coastal values (3, 7, and ice variants 11, 15) are **simplified to 2 (land)** in final NetCDF output.

### Ice-Modified Values (Dynamic, Date-Dependent)

When ice concentration > 0% is detected in OSI-SAF data, **bit 3 (value 8) is added** to the base mask:

| Base Value | Base Meaning | Ice Added | Final Value | Binary | Final Meaning |
|------------|--------------|-----------|-------------|--------|---------------|
| **1** | Open sea | +8 | **9** | `1001b` | Open sea with ice |
| **3** | Coast | +8 | **11** | `1011b` | Coast with ice → **simplified to 2** |
| **5** | Open lake | +8 | **13** | `1101b` | Open lake with ice |
| **7** | Lake shore | +8 | **15** | `1111b` | Lake shore with ice → **simplified to 2** |

### Final NetCDF Output Values

After post-processing, shoreline variants are collapsed to simple land:

| Value | Binary | Meaning | Typical Usage |
|-------|--------|---------|---------------|
| **1** | `0001b` | Open sea (no ice) | Most ocean pixels year-round |
| **2** | `0010b` | Land | All land including coasts and shores |
| **5** | `0101b` | Open lake (no ice) | Great Lakes, Caspian Sea (summer) |
| **9** | `1001b` | Open sea with ice | Arctic/Antarctic seasonal ice zones |
| **13** | `1101b` | Open lake with ice | Frozen Great Lakes (winter) |

### Seasonal Variation

**Summer (July-September, Northern Hemisphere):**
```
Value 1 (ocean):      ~71% of pixels
Value 2 (land):       ~29% of pixels
Value 5 (lake):       <0.1% of pixels
Value 9 (ice ocean):  ~0-2% (minimal Arctic ice)
Value 13 (ice lake):  0% (no frozen lakes)
```

**Winter (January-March, Northern Hemisphere):**
```
Value 1 (ocean):      ~64% of pixels
Value 2 (land):       ~29% of pixels
Value 5 (lake):       <0.05% of pixels (some frozen)
Value 9 (ice ocean):  ~6-7% (extensive Arctic/Antarctic ice)
Value 13 (ice lake):  <0.01% (frozen Great Lakes)
```

## Processing Pipeline

### Step 1: Static Mask Generation

**Historical Process (not in current repo):**
- Tool: `grids/gmt/maskbin2gds.m`
- Input: GSHHS (Global Self-consistent Hierarchical High-resolution Shoreline) database
- Output: `maskGLOBp01deg.gds`, `maskGlob1km.gds`
- Values: 1, 2, 3, 5, 7 (base land/water classification)

**Mask Characteristics:**
- Resolution: 0.01° (~1 km at equator)
- Coverage: Global (-180° to +180° lon, -90° to +90° lat)
- Data type: int8
- Static (does not change with date)

### Step 2: Ice Data Integration

**Tool:** `makeicefiles.m` → `saf2bip.m`

**Input:**
- Static mask file (`maskGLOBp01deg.gds`)
- OSI-SAF ice concentration data:
  - Northern Hemisphere: `ice_conc_nh_polstere-100_multi_YYYYMMDD1200.nc`
  - Southern Hemisphere: `ice_conc_sh_polstere-100_multi_YYYYMMDD1200.nc`

**Processing Steps:**

1. **Download ice data** via `readosisafice()`
   - Source: EUMETSAT OSI-SAF FTP server
   - Fallback: Up to 10 days backward if current day unavailable

2. **Quality control:**
   - Reject ice concentration < 30% (unreliable)
   - Reject ice concentration > 100% (invalid)
   - Fill polar regions (lat ≥ 87.7°N/S) with 100% ice

3. **Grid mapping:**
   - Use pre-computed indices to map OSI-SAF polar grid → MUR global grid
   - Interpolate to 0.01° resolution

4. **Ice flag addition:**
   ```matlab
   % Add bit 3 (value 8) where ice concentration > 0%
   knx = find(icemap > 0 & mask == 1);
   if length(knx), mask(knx) = 9; end;  % Ocean with ice

   knx = find(icemap > 0 & mask == 3);
   if length(knx), mask(knx) = 11; end;  % Coast with ice

   knx = find(icemap > 0 & mask == 5);
   if length(knx), mask(knx) = 13; end;  % Lake with ice
   ```

**Output:**
- `.gds` file: `landiceP01_YYYY_DDD.gds.gz` (land/ice mask)
- `.bip` file: `G10_YYYY_DDD.bip` (ice SST points for MRVA)

**Daily Update:** Ice mask regenerated every day (no caching)

### Step 3: NetCDF Output Generation [PENDING]

**Tool:** `csp2nc4a.m` (MRVA post-processing)

**Processing:**
1. Read daily landice mask file
2. **Simplify shoreline values:**
   ```matlab
   mask(mask == 3) = 2;   % Coast → land
   mask(mask == 7) = 2;   % Lake shore → land
   mask(mask == 11) = 2;  % Coast+ice → land
   mask(mask == 15) = 2;  % Complex → land
   ```
3. Write to NetCDF with CF-compliant metadata

**NetCDF Attributes:**
```
mask:valid_min = 1
mask:valid_max = 31
mask:flag_masks = 1, 2, 4, 8, 16
mask:flag_meanings = "open_sea land open_lake open_sea_with_ice_in_the_grid open_lake_with_ice_in_the_grid"
mask:comment = "mask can be used to further filter the data."
```

## Usage Examples

### Example 1: Extract Open Ocean SST (No Ice, No Land)

```python
import xarray as xr
import numpy as np

# Load MUR SST NetCDF file
ds = xr.open_dataset('20250211090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc')
mask = ds['mask'].values
sst = ds['analysed_sst'].values

# Method 1: Exact value
ocean_sst = sst[mask == 1]

# Method 2: Bitwise (more flexible)
is_ocean = ((mask & 2) == 0) & ((mask & 8) == 0)  # Not land, not ice
ocean_sst = sst[is_ocean]

print(f"Ocean SST: mean={ocean_sst.mean():.2f} K, std={ocean_sst.std():.2f} K")
```

### Example 2: Identify Ice-Covered Regions

```python
# All ice pixels (ocean + lake)
ice_mask = (mask & 8) != 0
ice_sst = sst[ice_mask]

# Ice-covered ocean only
ice_ocean_mask = (mask == 9)
ice_ocean_sst = sst[ice_ocean_mask]

# Ice-covered lakes only
ice_lake_mask = (mask == 13)
ice_lake_sst = sst[ice_lake_mask]

# Calculate ice extent
ice_pixel_count = np.sum(ice_mask)
pixel_area_km2 = 1.0  # Approximate at equator
ice_extent_km2 = ice_pixel_count * pixel_area_km2

print(f"Ice extent: {ice_extent_km2 / 1e6:.2f} million km²")
```

### Example 3: Exclude Coastal Pixels

```python
from scipy.ndimage import binary_dilation

# All coast is marked as land (value 2) after simplification
land_mask = (mask == 2)

# Create 3-pixel coastal buffer
coast_buffer = binary_dilation(land_mask, iterations=3)

# Extract offshore ocean only
offshore_mask = (mask == 1) & ~coast_buffer
offshore_sst = sst[offshore_mask]

print(f"Offshore ocean pixels: {np.sum(offshore_mask)}")
```

### Example 4: Lake Analysis

```python
# Extract all lake pixels (frozen or unfrozen)
lake_mask = (mask == 5) | (mask == 13)
lake_sst = sst[lake_mask]

# Separate by ice status
lake_open = sst[mask == 5]
lake_frozen = sst[mask == 13]

print(f"Open lakes: {len(lake_open)} pixels, mean SST={lake_open.mean():.2f} K")
print(f"Frozen lakes: {len(lake_frozen)} pixels, mean SST={lake_frozen.mean():.2f} K")

# Identify frozen fraction
frozen_fraction = len(lake_frozen) / (len(lake_open) + len(lake_frozen))
print(f"Frozen lake fraction: {frozen_fraction:.1%}")
```

### Example 5: Create Custom Mask

```python
# Define custom ocean region (tropical Pacific)
lat = ds['lat'].values
lon = ds['lon'].values

# Create meshgrid
lon_grid, lat_grid = np.meshgrid(lon, lat)

# Define region bounds
tropical_pacific = (
    (lat_grid >= -30) & (lat_grid <= 30) &
    (lon_grid >= 120) & (lon_grid <= -80) &
    (mask == 1)  # Ocean only
)

tropical_sst = sst[tropical_pacific]
print(f"Tropical Pacific SST: {tropical_sst.mean():.2f} K")
```

## Data Validation

### Expected Value Distribution

For a typical global MUR file (36000 × 18000 pixels):

| Value | % of Pixels | Typical Count | Seasonal Variation |
|-------|-------------|---------------|--------------------|
| **1** (Ocean) | ~71% | ~460M | Stable |
| **2** (Land) | ~29% | ~188M | Stable |
| **5** (Lake) | <0.1% | ~500K | Stable |
| **9** (Ice ocean) | 0-7% | 0-45M | High (winter max) |
| **13** (Ice lake) | <0.01% | 0-50K | High (frozen lakes) |

### Quality Check Function

```python
def validate_mask(mask):
    """Validate MUR land/ice mask values."""
    import numpy as np

    valid_values = {1, 2, 5, 9, 13}
    unique_vals = set(np.unique(mask))

    # Check for invalid values
    invalid = unique_vals - valid_values
    if invalid:
        print(f"❌ Invalid mask values found: {invalid}")
        return False

    # Check ocean percentage (should be ~71%)
    ocean_pct = 100 * np.sum(mask == 1) / mask.size
    if not (60 < ocean_pct < 80):
        print(f"⚠️ Ocean percentage unusual: {ocean_pct:.1f}% (expected ~71%)")

    # Check land percentage (should be ~29%)
    land_pct = 100 * np.sum(mask == 2) / mask.size
    if not (20 < land_pct < 40):
        print(f"⚠️ Land percentage unusual: {land_pct:.1f}% (expected ~29%)")

    # Print statistics
    print(f"✅ Mask validation passed")
    print(f"   Ocean (1):     {ocean_pct:.2f}%")
    print(f"   Land (2):      {land_pct:.2f}%")
    print(f"   Lake (5):      {100*np.sum(mask==5)/mask.size:.3f}%")
    print(f"   Ice ocean (9): {100*np.sum(mask==9)/mask.size:.2f}%")
    print(f"   Ice lake (13): {100*np.sum(mask==13)/mask.size:.3f}%")

    return True

# Example usage
ds = xr.open_dataset('mur_sst.nc')
validate_mask(ds['mask'].values)
```

### Physical Consistency Checks

```python
def check_ice_sst_consistency(sst, mask):
    """Verify that ice-covered pixels have appropriate SST."""
    import numpy as np

    # Ice pixels should have SST near freezing (~271-273 K)
    ice_mask = (mask & 8) != 0
    ice_sst = sst[ice_mask]

    # Check range
    min_ice_sst = ice_sst.min()
    max_ice_sst = ice_sst.max()

    if min_ice_sst < 270:
        print(f"⚠️ Ice SST too cold: {min_ice_sst:.2f} K")

    if max_ice_sst > 274:
        print(f"⚠️ Ice SST too warm: {max_ice_sst:.2f} K")

    print(f"Ice SST range: {min_ice_sst:.2f} - {max_ice_sst:.2f} K")
    print(f"Ice SST mean: {ice_sst.mean():.2f} K")
```

## File Formats

### .gds File Structure (Fortran Binary)

**Layout:**
```
Record 1: ii, jj (int32 × 2)                    - Grid dimensions
Record 2: mask(ii,jj), lon(ii), lat(jj) (bytes) - int8 array + float32 arrays
Record 3: icemap(ii,jj) (int8)                  - Ice concentration [0-100]
```

**Details:**
- `ii`, `jj`: Grid dimensions (e.g., 36000 × 18000 for 0.01° global)
- `mask`: Land/ice mask values (int8)
- `lon`: Longitude array (float32, -180 to +180)
- `lat`: Latitude array (float32, -90 to +90)
- `icemap`: Ice concentration (int8, 0-100% or -1 for no ice)

### Reading .gds in Python

```python
import struct
import numpy as np

def read_gds_file(filename):
    """Read MUR land/ice .gds file."""
    with open(filename, 'rb') as f:
        # Read grid dimensions (Fortran record)
        rec_len = struct.unpack('i', f.read(4))[0]
        ii, jj = struct.unpack('ii', f.read(8))
        rec_len_end = struct.unpack('i', f.read(4))[0]
        assert rec_len == rec_len_end, "Record length mismatch"

        print(f"Grid dimensions: {ii} × {jj}")

        # Read mask, lon, lat
        rec_len = struct.unpack('i', f.read(4))[0]
        mask = np.frombuffer(f.read(ii * jj), dtype='int8').reshape((jj, ii))
        lon = np.frombuffer(f.read(ii * 4), dtype='float32')
        lat = np.frombuffer(f.read(jj * 4), dtype='float32')
        rec_len_end = struct.unpack('i', f.read(4))[0]

        # Read icemap
        rec_len = struct.unpack('i', f.read(4))[0]
        icemap = np.frombuffer(f.read(ii * jj), dtype='int8').reshape((jj, ii))
        rec_len_end = struct.unpack('i', f.read(4))[0]

    return {
        'mask': mask,
        'lon': lon,
        'lat': lat,
        'icemap': icemap
    }

# Example usage
data = read_gds_file('/nas2/gds/2025/G10_2025_042.gds')
print(f"Mask values: {np.unique(data['mask'])}")
print(f"Ice coverage: {np.sum(data['icemap'] > 0)} pixels")
```

### Writing .gds in Python

```python
def write_gds_file(filename, mask, lon, lat, icemap):
    """Write MUR land/ice .gds file."""
    jj, ii = mask.shape

    with open(filename, 'wb') as f:
        # Write grid dimensions
        rec_len = 8  # 2 × int32
        f.write(struct.pack('i', rec_len))
        f.write(struct.pack('ii', ii, jj))
        f.write(struct.pack('i', rec_len))

        # Write mask, lon, lat
        rec_len = ii * jj + ii * 4 + jj * 4
        f.write(struct.pack('i', rec_len))
        f.write(mask.astype('int8').tobytes())
        f.write(lon.astype('float32').tobytes())
        f.write(lat.astype('float32').tobytes())
        f.write(struct.pack('i', rec_len))

        # Write icemap
        rec_len = ii * jj
        f.write(struct.pack('i', rec_len))
        f.write(icemap.astype('int8').tobytes())
        f.write(struct.pack('i', rec_len))

# Example: Create custom mask
mask = np.ones((18000, 36000), dtype='int8')  # All ocean
icemap = np.zeros((18000, 36000), dtype='int8') - 1  # No ice
lon = np.linspace(-180, 180, 36000, dtype='float32')
lat = np.linspace(-90, 90, 18000, dtype='float32')

write_gds_file('custom_mask.gds', mask, lon, lat, icemap)
```

---

## Summary

The MUR land/ice mask encoding:

- **Compact representation:** Single int8 value encodes 4 surface properties
- **Bitwise flags:** Allows flexible filtering (ocean, land, lake, ice)
- **Daily updates:** Ice extent changes daily based on OSI-SAF data
- **Simplified output:** Coastal complexity reduced to land (value 2) in final products
- **Quality assured:** Expected value distributions validate processing

**Key Values:**
- `1` - Open ocean (most common, ~71% of pixels)
- `2` - Land (all land including coasts, ~29%)
- `5` - Lakes (Great Lakes, etc., <0.1%)
- `9` - Ice-covered ocean (Arctic/Antarctic, seasonal)
- `13` - Frozen lakes (winter only, rare)

---

## References

- [OVERVIEW.md](OVERVIEW.md) - System architecture
- [landice/README.md](../landice/README.md) - Land/ice processing details
- OSI-SAF ice data: https://osi-saf.eumetsat.int/
- GHRSST format: https://www.ghrsst.org/

---

*Last Updated: 2025-01-18*
*Documentation Version: 1.0*
