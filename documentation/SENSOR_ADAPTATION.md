# Adding New Sensors to MUR L2P Pipeline

## Introduction

This document describes how to integrate new satellite sensors into the MUR L2P preprocessing pipeline. It covers the requirements for L2P input data, the output format specifications, sensor configuration parameters, and the complete integration workflow.

## Table of Contents

1. [L2P Input Requirements](#l2p-input-requirements)
2. [L2P Output Specifications](#l2p-output-specifications)
3. [Sensor Configuration Parameters](#sensor-configuration-parameters)
4. [Integration Workflow](#integration-workflow)
5. [Testing and Validation](#testing-and-validation)
6. [Examples](#examples)

## L2P Input Requirements

### Data Format

**Required:** GHRSST Level 2P (L2P) NetCDF files

**Standard:** Group for High Resolution SST (GHRSST) Data Processing Specification v2.0

**Key NetCDF Variables (Required):**

| Variable | Units | Description | Typical Range |
|----------|-------|-------------|---------------|
| `sea_surface_temperature` | Kelvin | SST observations | 270-320 K |
| `lat` | degrees_north | Latitude | -90 to +90 |
| `lon` | degrees_east | Longitude | -180 to +180 |
| `time` | seconds since 1981-01-01 | Observation time | Unix timestamp |
| `quality_level` or `l2p_flags` | flag | Data quality indicator | Integer flags |
| `sst_dtime` | seconds | Time offset from reference | -43200 to +43200 |

**Optional but Recommended:**

| Variable | Purpose | Fallback |
|----------|---------|----------|
| `sses_bias` | SST bias estimate | 0.0 (no bias) |
| `sses_standard_deviation` | Error estimate | Default: 0.6 K |
| `proximity_confidence` | Cloud/land proximity | Use quality_level |

**File Naming Convention:**

GHRSST standard naming:
```
YYYYMMDDHHMMSS-PROVIDER-L2P_GHRSST-SSTtype-SENSOR-platform-version.nc

Example:
20250808000000-JPL-L2P_GHRSST-SSTskin-MODIS_A-D-v02.0-fv01.0.nc
```

### Data Source

**NASA PO.DAAC (Physical Oceanography DAAC):**
- URL: https://podaac.jpl.nasa.gov/
- Download tool: `podaac-data-subscriber`
- Authentication: NASA Earthdata Login required
- Data format: GHRSST-compliant NetCDF

**Collection Requirements:**
- Must be available via PO.DAAC subscription service
- Regular updates (daily orbital data)
- Metadata consistency (GHRSST compliance)

### Sensor Characteristics

**Before adding a new sensor, document:**

1. **Platform information:**
   - Satellite name
   - Orbit type (polar, geostationary)
   - Overpass times (local time at equator)

2. **Instrument specifications:**
   - Sensor type (microwave, infrared, multi-spectral)
   - Spatial resolution (nadir and edge-of-swath)
   - Swath width
   - Measurement principle (skin vs. subskin temperature)

3. **Data characteristics:**
   - Typical granule count per day
   - Cloud impact (infrared sensors)
   - All-weather capability (microwave sensors)
   - Quality flag interpretation

4. **Temporal characteristics:**
   - Data latency (observation to availability)
   - Reprocessing schedule
   - Stability latency (how long until data is finalized)

## L2P Output Specifications

### BIC File Format

**Output File:** `.bic.gz` (Binary Input with Confidence, gzip compressed)

**Naming Convention:**
```
{REGION}_{SENSOR}_{YEAR}_{DOY}.bic.gz

Example:
G10_MODISA_2025_042.bic.gz
```

**Binary Structure:**

The `.bic` file is a Fortran-compatible unformatted binary file with the following structure:

```fortran
! Header record
write(unit) nobs  ! Integer: number of observations

! Data records (one per observation)
do i = 1, nobs
    write(unit) lon(i)    ! Real*4: longitude (degrees East, -180 to +180)
    write(unit) lat(i)    ! Real*4: latitude (degrees North, -90 to +90)
    write(unit) sst(i)    ! Real*4: SST (degrees Celsius)
    write(unit) hour(i)   ! Real*4: hours from analysis time (-48 to +48)
    write(unit) bias(i)   ! Real*4: bias correction (degrees C)
    write(unit) rms(i)    ! Real*4: RMS error estimate (degrees C)
    write(unit) qflag(i)  ! Real*4: quality flag (sensor-specific)
end do
```

**Data Requirements:**

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `lon` | Real*4 | -180 to +180 | Longitude in degrees East |
| `lat` | Real*4 | -90 to +90 | Latitude in degrees North |
| `sst` | Real*4 | -2 to +45 | SST in degrees Celsius |
| `hour` | Real*4 | -48 to +48 | Time offset from analysis (hours) |
| `bias` | Real*4 | -2 to +2 | Bias correction (Celsius) |
| `rms` | Real*4 | 0.1 to 2.0 | Error standard deviation (Celsius) |
| `qflag` | Real*4 | sensor-specific | Quality/confidence indicator |

**Quality Standards:**

- SST values must be physically realistic (-2°C to 45°C)
- Missing/invalid data must be filtered out (not written to BIC)
- Time offsets should be accurate (impact temporal weighting)
- Bias and error estimates should be sensor-appropriate

**Compression:**

- Files are gzip compressed (`.gz`)
- Typical compression ratio: 3:1 to 5:1
- Original BIC size: 150-2000 MB
- Compressed size: 50-500 MB

### Companion Files

**L2Plist File:** `L2Plist_{REGION}_{SENSOR}_{YEAR}_{DOY}.txt`

**Purpose:** Track source granules used in processing

**Format:** Plain text, one granule filename per line

**Example:**
```
20250211000000-JPL-L2P_GHRSST-SSTskin-MODIS_A-D-v02.0-fv01.0.nc
20250211001500-JPL-L2P_GHRSST-SSTskin-MODIS_A-D-v02.0-fv01.0.nc
20250211003000-JPL-L2P_GHRSST-SSTskin-MODIS_A-D-v02.0-fv01.0.nc
```

**Uses:**
- Quality assurance (verify input granules)
- Reprocessing traceability
- Data provenance documentation

## Sensor Configuration Parameters

### Scale Parameters (La/Lb)

**Definition:**
- `La` (Lower scale): Minimum scale at which sensor contributes to MRVA
- `Lb` (Upper scale): Maximum scale at which sensor contributes to MRVA

**Scale-to-Resolution Mapping:**

| Scale | Grid Spacing | Effective Resolution | Typical Sensors |
|-------|--------------|---------------------|-----------------|
| L=2 | ~11.25° | ~1250 km | All sensors |
| L=3-5 | ~5.6° to ~1.4° | ~625 to ~156 km | All sensors |
| L=6-8 | ~0.7° to ~0.17° | ~78 to ~19 km | Medium+ res sensors |
| L=9 | ~0.09° | ~10 km | High-res sensors only |
| L=10-12 | ~0.045° to ~0.022° | ~5 to ~2.5 km | Highest-res sensors |

**Guideline for Setting La/Lb:**

```
1. Determine sensor pixel size at nadir (in km)

2. Set Lb based on resolution:
   - If pixel_size > 20 km:      Lb = 8  (exclude from fine scales)
   - If 10 km < pixel_size ≤ 20: Lb = 9
   - If 5 km < pixel_size ≤ 10:  Lb = 10
   - If pixel_size ≤ 5 km:       Lb = 11 or 12 (highest res)

3. Set La = 2 (all sensors contribute to large scales)

4. Rationale: Prevent aliasing by excluding sensors at scales
   finer than their native resolution
```

**Current Sensor Configurations:**

| Sensor | Type | Resolution | La | Lb | Scales Used |
|--------|------|------------|----|----|-------------|
| IQUAM0 (buoys) | In-situ | Point | 2 | 8 | 2-8 |
| AMSR2R | Microwave | ~25 km | 2 | 8 | 2-8 |
| MODISA | Infrared | ~1 km | 2 | 12 | 2-12 |
| MODIST | Infrared | ~1 km | 2 | 12 | 2-12 |
| AVMTBG | Infrared | ~1-4 km | 2 | 9 | 2-9 |
| Ice SST | Model | ~10 km | 2 | 9 | 2-9 |

**Example: Adding a new 5km sensor:**
```
Sensor: VIIRS (Visible Infrared Imaging Radiometer Suite)
Resolution: ~750m nadir, ~1.5km edge-of-swath (average ~1 km)
Recommended: La=2, Lb=12 (same as MODIS)
Rationale: High resolution, suitable for all scales
```

**Example: Adding a coarse sensor:**
```
Sensor: SMAP (Soil Moisture Active Passive) SSS/SST
Resolution: ~40 km
Recommended: La=2, Lb=7
Rationale: Too coarse for scales > L=7 (~39 km grid)
```

### Quality Filtering Parameters

**Minimum Confidence Value:**

Purpose: Filter poor-quality observations

**Configuration in SensorTable.m:**
```matlab
case 'NEWSENSOR'
    minConfValue = 5;  % Sensor-dependent threshold
```

**Guidelines:**

| Sensor Type | Typical Threshold | Rationale |
|-------------|------------------|-----------|
| **Infrared** | 4-5 | Strict (cloud contamination risk) |
| **Microwave** | 3-4 | Moderate (all-weather) |
| **Multi-spectral** | 5 | Strict (complex QC) |

**Quality Flag Interpretation:**

GHRSST standard quality levels:
- **0:** No data
- **1:** Bad data (failed QC)
- **2:** Worst quality
- **3:** Low quality
- **4:** Acceptable quality
- **5:** Best quality

**Proximity Confidence (if available):**
- Additional filtering for cloud/land proximity
- Typically used in conjunction with quality_level

### Stability Latency

**Definition:** Time period (in days) before sensor data is considered "stable" and no longer needs reprocessing in NRT mode

**Purpose:**
- Account for data provider reprocessing
- Handle delayed quality control updates
- Ensure final product uses mature data

**Current Values:**

| Sensor | Stability (days) | Rationale |
|--------|-----------------|-----------|
| MODISA | 2 | Standard product, 2-day finalization |
| MODIST | 3 | Additional Terra-specific processing |
| AMSR2R | 2 | Microwave product, fast turnaround |
| AVMTBG | 2 | Standard NAVO processing |

**How to Determine for New Sensor:**

1. **Consult provider documentation:**
   - PO.DAAC dataset landing page
   - Processing algorithm description
   - Reprocessing schedule

2. **Empirical testing:**
   - Download data for same day over 7 days
   - Compare file hashes or observation counts
   - Determine when changes stabilize

3. **Conservative estimate:**
   - If uncertain, use 3 days (safe default)
   - Can reduce after operational experience

**Impact:**

```
Stability = 2 days:
  Processing day 042:
    Day 042: Age 0 → Reprocess (fresh)
    Day 041: Age 1 → Reprocess (age < 2)
    Day 040: Age 2 → Use cache (stable)

Stability = 3 days:
  Processing day 042:
    Day 042: Age 0 → Reprocess (fresh)
    Day 041: Age 1 → Reprocess (age < 3)
    Day 040: Age 2 → Reprocess (age < 3)
    Day 039: Age 3 → Use cache (stable)
```

Higher stability latency = more reprocessing = slower NRT but better quality

### Bias and Error Estimates

**Default Error (if not in L2P file):**

```matlab
default_sst_error = 0.6;  % Kelvin (conservative)
```

**Sensor-Specific Tuning:**

If available from validation studies:
```matlab
switch upper(SensorName)
    case 'NEWSENSOR'
        default_error = 0.4;  % Low-error sensor
        % Apply scaling if needed
    otherwise
        default_error = 0.6;  % Conservative default
end
```

**Bias Handling:**

- Prefer sensor-provided `sses_bias` field
- If unavailable, use 0.0 (no bias assumption)
- For systematic bias, consider external correction tables

## Integration Workflow

### Step 1: Assess Sensor Suitability

**Checklist:**

- [ ] GHRSST L2P format available from PO.DAAC
- [ ] Spatial resolution documented (≤ 25 km preferred)
- [ ] Temporal coverage adequate (daily global or near-global)
- [ ] Quality flags well-defined
- [ ] Data latency acceptable (< 12 hours for NRT)
- [ ] License compatible with MUR distribution

### Step 2: Update SensorTable.m

**Location:** `mur/l2p/src/SensorTable.m`

**Add new case:**

```matlab
function [l2pnames,minConfValue,cmd,subdir]=SensorTable(SensorName)

% Existing sensors...

  case 'NEWSENSOR',  % e.g., 'VIIRS'
    % File pattern to match L2P granules
    l2pnames   = {'*.nc'};

    % Minimum quality level (GHRSST standard: 0-5)
    minConfValue = 5;  % Adjust based on sensor

    % Decompression command ('' = no compression, 'cat' = standard)
    cmd = 'cat';

    % Subdirectory path (legacy, informational only)
    subdir='GDS2/L2P/NEWSENSOR/PROVIDER/version';

end;  % switch
```

**Parameters to configure:**

1. **l2pnames:** Filename pattern(s) to match granules
   - Use wildcards: `'*.nc'` (all .nc files)
   - Multiple patterns: `{'*_v8.2_*.nc','*_rt_*.nc'}` (AMSR2R example)

2. **minConfValue:** Quality threshold
   - Higher = stricter filtering
   - Recommend 4-5 for infrared, 3-4 for microwave

3. **cmd:** Decompression command
   - `''` for uncompressed files
   - `'cat'` for standard compression
   - Special handling if needed

4. **subdir:** Legacy path structure (not used in containerized version)

### Step 3: Configure MRVA Parameters

**Location:** `cyc4/mrva4com.m` (MRVA configuration file)

**Add sensor to bipfile array:**

```matlab
% Existing configuration
% bipfile(1,m) = La (minimum scale)
% bipfile(2,m) = Lb (maximum scale)

% Sensor indices
IQUAM0_idx  = 1;
AMSR2R_idx  = 2;
MODISA_idx  = 3;
MODIST_idx  = 4;
AVMTBG_idx  = 5;
NEWSENSOR_idx = 6;  % New sensor index

% Scale limits
bipfile(1, NEWSENSOR_idx) = 2;   % La (start scale)
bipfile(2, NEWSENSOR_idx) = 10;  % Lb (end scale)

% Sensor names (for file lookup)
sensor_names{NEWSENSOR_idx} = 'NEWSENSOR';
```

**Update temporal decay if needed:**

```matlab
% Default decay parameters (hours) - one per scale
decay = [48, 48, 48, 48, 48, 48, 42, 36, 30, 24, 18, 12];
%        L2  L3  L4  L5  L6  L7  L8  L9 L10 L11 L12 L13

% Sensor-specific decay (if different from default)
% Usually not needed unless sensor has unique temporal characteristics
```

### Step 4: Update Pipeline Orchestrator

**Location:** `mur/run_mur_pipeline.py`

**Add sensor to configuration:**

```python
# L2P sensor configuration
L2P_SENSORS = {
    'AMSR2R': {
        'collection': 'AMSR2-REMSS-L2P-v8.2',
        'stability_latency': 2,
        'dayrange': 2
    },
    'MODISA': {
        'collection': 'MODIS_A-JPL-L2P-v2019.0',
        'stability_latency': 2,
        'dayrange': 2
    },
    'MODIST': {
        'collection': 'MODIS_T-JPL-L2P-v2019.0',
        'stability_latency': 3,
        'dayrange': 2
    },
    'AVMTBG': {
        'collection': 'AVHRRMTB_G-NAVO-L2P-v2.0',
        'stability_latency': 2,
        'dayrange': 2
    },
    'NEWSENSOR': {  # ADD NEW SENSOR HERE
        'collection': 'NEWSENSOR-PROVIDER-L2P-vX.Y',
        'stability_latency': 2,  # Adjust based on testing
        'dayrange': 2
    }
}
```

**Add to processing loop:**

```python
def run_l2p_processing(year, doy, region, mode):
    """Process L2P sensors"""
    for sensor_name, config in L2P_SENSORS.items():
        print(f"Processing {sensor_name}...")

        # Determine rewrite flag based on stability
        rewrite = should_rewrite(doy, config['stability_latency'], mode)

        # Run L2P container
        run_l2p_container(
            sensor=sensor_name,
            year=year,
            doy=doy,
            region=region,
            rewrite=rewrite,
            dayrange=config['dayrange']
        )
```

### Step 5: Setup Download Infrastructure

**Option 1: Hourly Cron (Production Pattern)**

Create download script:
```bash
#!/bin/bash
# download_newsensor.sh

podaac-data-subscriber \
    -c NEWSENSOR-PROVIDER-L2P-vX.Y \
    -d /nas2/source/podaac/NEWSENSOR \
    --start-date $(date -u +%Y-%m-%dT00:00:00Z) \
    --end-date $(date -u +%Y-%m-%dT23:59:59Z) \
    --verbose
```

Add to crontab:
```cron
# Download NEWSENSOR data hourly
0 * * * * /path/to/download_newsensor.sh >> /var/log/newsensor_download.log 2>&1
```

**Option 2: On-Demand Download**

Integrate into pipeline orchestrator:
```python
def download_l2p_data(sensor, year, doy, dayrange):
    """Download L2P data for processing window"""
    collection = L2P_SENSORS[sensor]['collection']

    start_doy = doy - dayrange
    end_doy = doy + dayrange

    cmd = [
        'podaac-data-subscriber',
        '-c', collection,
        '-d', f'/nas2/source/podaac/{sensor}',
        '--start-date', doy_to_date(year, start_doy),
        '--end-date', doy_to_date(year, end_doy)
    ]

    subprocess.run(cmd, check=True)
```

### Step 6: Rebuild L2P Container

**Rebuild to include SensorTable changes:**

```bash
cd mur/l2p
docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..
```

**Tag for versioning:**
```bash
docker tag mur-l2p:latest mur-l2p:v1.1-newsensor
```

**Push to registry (if using):**
```bash
docker push ghcr.io/nasa-jpl/mur-l2p:latest
```

## Testing and Validation

### Unit Testing

**Test 1: Single Granule Processing**

```bash
# Download single test granule
podaac-data-subscriber \
    -c NEWSENSOR-PROVIDER-L2P-vX.Y \
    -d /tmp/test_newsensor \
    --start-date 2025-02-11T00:00:00Z \
    --end-date 2025-02-11T00:10:00Z

# Process with container
docker run --rm \
    --shm-size=512M \
    -v /tmp/test_newsensor:/input \
    -v /tmp/test_output:/output \
    mur-l2p:latest \
    NEWSENSOR Global /input /output 2025 042 1

# Verify output
ls -lh /tmp/test_output/
# Should see: Global_NEWSENSOR_2025_042.bic.gz
```

**Test 2: BIC File Validation**

```python
import struct
import gzip

def validate_bic_file(filename):
    """Validate BIC file structure and contents"""
    with gzip.open(filename, 'rb') as f:
        # Read observation count
        nobs_bytes = f.read(4)
        nobs = struct.unpack('i', nobs_bytes)[0]
        print(f"Number of observations: {nobs}")

        # Read first observation
        for field in ['lon', 'lat', 'sst', 'hour', 'bias', 'rms', 'qflag']:
            value_bytes = f.read(4)
            value = struct.unpack('f', value_bytes)[0]
            print(f"{field}: {value}")

        # Validate ranges
        assert -180 <= lon <= 180, "Longitude out of range"
        assert -90 <= lat <= 90, "Latitude out of range"
        assert -2 <= sst <= 45, "SST out of range"
        assert -48 <= hour <= 48, "Time offset out of range"

validate_bic_file('/tmp/test_output/Global_NEWSENSOR_2025_042.bic.gz')
```

**Test 3: Observation Count Sanity**

```python
def count_bic_observations(filename):
    """Count observations in BIC file"""
    with gzip.open(filename, 'rb') as f:
        nobs_bytes = f.read(4)
        nobs = struct.unpack('i', nobs_bytes)[0]
    return nobs

# Expected observation counts (rough estimates)
EXPECTED_COUNTS = {
    'AMSR2R': (50_000, 500_000),       # Coarse resolution, fewer obs
    'MODISA': (1_000_000, 10_000_000), # High res, many obs
    'NEWSENSOR': (100_000, 5_000_000)  # Adjust based on sensor
}

nobs = count_bic_observations('Global_NEWSENSOR_2025_042.bic.gz')
min_expected, max_expected = EXPECTED_COUNTS['NEWSENSOR']
assert min_expected <= nobs <= max_expected, f"Unexpected obs count: {nobs}"
```

### Integration Testing

**Test 4: Full Day Processing**

```bash
# Process full day with all sensors including new sensor
cd mur/
python run_mur_pipeline.py 2025 042 G10 nrt

# Verify all BIC files created
ls -lh /nas2/bic/*/2025/G10_*_2025_042.bic.gz

# Check logs for errors
grep -i error /var/log/mur_pipeline.log
```

**Test 5: Multi-Day Window**

```bash
# Process with ±2 day window
for doy in 040 041 042 043 044; do
    docker run --rm \
        -v /nas2/source/podaac/NEWSENSOR:/input \
        -v /nas2/bic/NEWSENSOR:/output \
        mur-l2p:latest \
        NEWSENSOR Global /input /output 2025 $doy 0
done

# Verify all days processed
ls /nas2/bic/NEWSENSOR/2025/ | grep -E '04[0-4]'
```

### Validation Against Existing Sensors

**Test 6: Comparison with MODIS**

If new sensor has similar resolution to MODIS, compare statistics:

```python
def compare_sensors(bic_file1, bic_file2, region='global'):
    """Compare SST statistics between two sensors"""
    import numpy as np

    def read_bic_sst(filename):
        sst_values = []
        with gzip.open(filename, 'rb') as f:
            nobs = struct.unpack('i', f.read(4))[0]
            for _ in range(nobs):
                lon, lat, sst = struct.unpack('fff', f.read(12))
                f.read(16)  # Skip hour, bias, rms, qflag
                sst_values.append(sst)
        return np.array(sst_values)

    sst1 = read_bic_sst(bic_file1)
    sst2 = read_bic_sst(bic_file2)

    print(f"Sensor 1: mean={sst1.mean():.2f}, std={sst1.std():.2f}")
    print(f"Sensor 2: mean={sst2.mean():.2f}, std={sst2.std():.2f}")
    print(f"Difference: {abs(sst1.mean() - sst2.mean()):.2f} °C")

    # Should be within ~1°C for similar sensor types
    assert abs(sst1.mean() - sst2.mean()) < 1.0, "Mean SST difference too large"

compare_sensors(
    '/nas2/bic/MODISA/2025/G10_MODISA_2025_042.bic.gz',
    '/nas2/bic/NEWSENSOR/2025/G10_NEWSENSOR_2025_042.bic.gz'
)
```

### Quality Assurance

**Test 7: Spatial Coverage**

```python
def check_spatial_coverage(bic_file):
    """Verify global coverage"""
    lons, lats = [], []

    with gzip.open(bic_file, 'rb') as f:
        nobs = struct.unpack('i', f.read(4))[0]
        for _ in range(nobs):
            lon, lat = struct.unpack('ff', f.read(8))
            lons.append(lon)
            lats.append(lat)
            f.read(20)  # Skip remaining fields

    # Check coverage
    lat_range = max(lats) - min(lats)
    lon_range = max(lons) - min(lons)

    print(f"Latitude range: {min(lats):.1f} to {max(lats):.1f} ({lat_range:.1f}°)")
    print(f"Longitude range: {min(lons):.1f} to {max(lons):.1f} ({lon_range:.1f}°)")

    # Global coverage should span most of -90 to +90, -180 to +180
    assert lat_range > 150, "Insufficient latitude coverage"
    assert lon_range > 300, "Insufficient longitude coverage"

check_spatial_coverage('/nas2/bic/NEWSENSOR/2025/G10_NEWSENSOR_2025_042.bic.gz')
```

**Test 8: Temporal Coverage**

```python
def check_temporal_distribution(bic_file):
    """Verify observations span 24 hours"""
    hours = []

    with gzip.open(bic_file, 'rb') as f:
        nobs = struct.unpack('i', f.read(4))[0]
        for _ in range(nobs):
            f.read(12)  # Skip lon, lat, sst
            hour = struct.unpack('f', f.read(4))[0]
            hours.append(hour)
            f.read(12)  # Skip bias, rms, qflag

    hour_range = max(hours) - min(hours)
    print(f"Time range: {min(hours):.1f} to {max(hours):.1f} hours ({hour_range:.1f} h)")

    # Should span close to 24 hours for daily data
    assert hour_range > 20, "Insufficient temporal coverage"

check_temporal_distribution('/nas2/bic/NEWSENSOR/2025/G10_NEWSENSOR_2025_042.bic.gz')
```

## Examples

### Example 1: VIIRS (High-Resolution Infrared)

**Sensor Characteristics:**
- Platform: NOAA-20, SNPP
- Type: Infrared radiometer
- Resolution: ~750m nadir
- Coverage: Global, polar orbit

**Configuration:**

**SensorTable.m:**
```matlab
case 'VIIRS',
    l2pnames   = {'*.nc'};
    minConfValue = 5;  % High quality only
    cmd = 'cat';
    subdir='GDS2/L2P/VIIRS/NOAA/v2';
```

**MRVA Configuration:**
```matlab
% Scale limits (high resolution like MODIS)
bipfile(1, VIIRS_idx) = 2;   % La
bipfile(2, VIIRS_idx) = 12;  % Lb
```

**Pipeline Configuration:**
```python
'VIIRS': {
    'collection': 'VIIRS_NPP-OSPO-L2P-v2.61',
    'stability_latency': 2,
    'dayrange': 2
}
```

### Example 2: SMAP (Coarse-Resolution Microwave)

**Sensor Characteristics:**
- Platform: SMAP satellite
- Type: Microwave radiometer
- Resolution: ~40 km
- Coverage: Global ocean, 3-day repeat

**Configuration:**

**SensorTable.m:**
```matlab
case 'SMAP',
    l2pnames   = {'*_L2P_*.nc'};
    minConfValue = 4;  % Microwave, relaxed threshold
    cmd = '';
    subdir='GDS2/L2P/SMAP/RSS/v5';
```

**MRVA Configuration:**
```matlab
% Scale limits (coarse resolution)
bipfile(1, SMAP_idx) = 2;   % La
bipfile(2, SMAP_idx) = 7;   % Lb (limit to ~39 km scales)
```

**Pipeline Configuration:**
```python
'SMAP': {
    'collection': 'SMAP_L2B_SSS-REMSS-v5.0',
    'stability_latency': 3,  # Longer processing time
    'dayrange': 3  # Wider window for 3-day repeat
}
```

### Example 3: Geostationary Sensor (Himawari-8)

**Sensor Characteristics:**
- Platform: Himawari-8 (geostationary)
- Type: Infrared imager
- Resolution: ~2 km
- Coverage: Asia-Pacific region only

**Special Considerations:**
- Regional coverage (not global)
- High temporal resolution (10-min updates)
- Many granules per day

**Configuration:**

**SensorTable.m:**
```matlab
case 'HIMAWARI8',
    l2pnames   = {'*.nc'};
    minConfValue = 5;
    cmd = 'cat';
    subdir='GDS2/L2P/AHI/JAXA/v2';
```

**MRVA Configuration:**
```matlab
% Scale limits (medium-high resolution)
bipfile(1, HIMAWARI8_idx) = 2;
bipfile(2, HIMAWARI8_idx) = 10;  % Good to ~5 km scales
```

**Pipeline Configuration:**
```python
'HIMAWARI8': {
    'collection': 'AHI-JAXA-L2P-v2',
    'stability_latency': 2,
    'dayrange': 1  # High temporal resolution, shorter window
}
```

**Regional Filtering (if needed):**
```matlab
% In l2p2bic.m, add regional filter
if strcmp(sensor, 'HIMAWARI8')
    % Only keep Asia-Pacific region
    valid_idx = lon >= 80 & lon <= 200 & lat >= -60 & lat <= 60;
    lon = lon(valid_idx);
    lat = lat(valid_idx);
    sst = sst(valid_idx);
    % ... filter other fields
end
```

---

## Summary

Adding a new sensor to the MUR L2P pipeline requires:

1. **Assessment:** Verify GHRSST L2P format and PO.DAAC availability
2. **Configuration:** Update SensorTable.m, MRVA parameters, pipeline orchestrator
3. **Scale Selection:** Set La/Lb based on sensor resolution
4. **Quality Filtering:** Configure minConfValue based on sensor QC
5. **Download Setup:** Establish cron or on-demand download
6. **Testing:** Validate BIC output, compare with existing sensors
7. **Deployment:** Rebuild container, update documentation

The modular design allows new sensors to be integrated with minimal code changes while maintaining consistency with the existing MUR preprocessing framework.

---

## References

- [OVERVIEW.md](OVERVIEW.md) - System architecture
- [ALGORITHM_FLOW.md](ALGORITHM_FLOW.md) - MRVA scale parameters
- [l2p/README.md](../l2p/README.md) - L2P processing details
- [GHRSST Data Specification](https://www.ghrsst.org) - L2P format standard

---

*Last Updated: 2025-01-18*
*Documentation Version: 1.0*
