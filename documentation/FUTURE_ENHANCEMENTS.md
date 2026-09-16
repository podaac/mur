# Future Enhancements and Considerations

## Introduction

This document describes features and enhancements that have been considered for the MUR SST processing system but are not currently implemented. Some of these features have preliminary groundwork in the codebase, while others represent potential improvements based on scientific requirements and operational experience.

**Status:** These features are documented for future reference but are **not part of the current operational system**. They should not be assumed to be available in the preprocessing pipeline or MRVA algorithm.

## Table of Contents

1. [Daytime Data Processing](#daytime-data-processing)
2. [ECMWF Wind-Based Filtering](#ecmwf-wind-based-filtering)
3. [REA Mode Full Implementation](#rea-mode-full-implementation)
4. [Additional Sensor Integration](#additional-sensor-integration)
5. [Processing Optimizations](#processing-optimizations)
6. [Quality Control Enhancements](#quality-control-enhancements)

---

## Daytime Data Processing

### Current State: Nighttime Only

**Implementation Status:** ❌ Not Implemented

**Current Approach:**
- MUR SST currently uses **nighttime-only observations** from infrared sensors
- Daytime data is **excluded during preprocessing** to avoid diurnal warming effects
- This filtering happens in the `makebiq` stage when converting BIC files to BIQ format

**Rationale for Nighttime-Only:**
- Infrared sensors measure **skin temperature** at the ocean surface
- During daytime, solar heating creates a warm surface layer (diurnal warm layer)
- This warm layer can be 1-3°C warmer than the subsurface **foundation temperature**
- Nighttime observations avoid this diurnal warming complication
- Foundation temperature is what oceanographers typically want for climate studies

### Proposed Enhancement: Daytime Data Integration

**Scientific Motivation:**
- Daytime observations could improve spatial coverage, especially in cloud-prone regions
- High-resolution satellites (MODIS, VIIRS) have many daytime passes
- Excluding daytime data reduces effective observation count by ~40-50%

**Technical Challenges:**

1. **Diurnal Warming Correction**
   - Need model to estimate diurnal warming magnitude
   - Depends on: solar radiation, wind speed, cloud cover, stratification
   - ECMWF provides some of these inputs (see next section)

2. **Foundation Temperature Conversion**
   - Convert skin temperature → foundation temperature
   - Foundation temp = skin temp - diurnal_warming_correction
   - Correction varies by time of day, season, latitude

3. **Sensor-Specific Handling**
   - Microwave sensors (AMSR2) less affected by diurnal cycle
   - Infrared sensors (MODIS, VIIRS) strongly affected
   - Need sensor-dependent correction strategies

**Preliminary Groundwork:**
- Code references in `makebiq` for daytime filtering exist
- Infrastructure for time-of-day metadata present in BIC files
- Would need wind speed input (see ECMWF section)

**Implementation Requirements:**

```
1. Diurnal Warming Model Integration
   - Select model (e.g., COARE, Gentemann et al., Fairall et al.)
   - Implement in MATLAB preprocessing
   - Validate against buoy observations

2. Wind Speed Input
   - Integrate ECMWF ERA5 wind data (see next section)
   - Or use satellite wind products (ASCAT, WindSat)

3. Quality Control
   - Flag uncertain corrections (low wind, high solar)
   - Monitor foundation temp consistency
   - Compare daytime vs nighttime residuals

4. Testing
   - Run parallel processing (nighttime-only vs. nighttime+daytime)
   - Validate against independent observations
   - Assess impact on product quality
```

**Estimated Effort:** 6-12 months (model selection, implementation, validation)

**Priority:** Medium (coverage improvement) vs. High (maintain current quality)

---

## ECMWF Wind-Based Filtering

### Current State: Not Implemented

**Implementation Status:** ❌ Not Implemented (Groundwork Only)

**Current Approach:**
- No wind-based filtering in operational system
- All quality-passed observations used regardless of wind conditions

**Rationale for Wind Filtering:**
- High winds (>10-15 m/s) can affect SST retrievals
- Rough seas increase uncertainty in satellite measurements
- Very low winds (<2 m/s) can lead to diurnal warm layers during daytime

### Proposed Enhancement: ECMWF ERA5 Wind Integration

**Purpose:**
- Filter observations under extreme wind conditions
- Enable diurnal warming corrections (for daytime data)
- Improve quality control for satellite retrievals

**Data Source:**
- **ECMWF ERA5 Reanalysis**
- Variables: 10m u/v wind components
- Resolution: 0.25° × 0.25° (global)
- Temporal: Hourly
- Latency: ~5 days (reanalysis), ~5 hours (operational forecast)

**Use Cases:**

1. **Quality Filtering (Conservative)**
   ```
   Reject observations where:
   - Wind speed > 15 m/s (high uncertainty in rough seas)
   - Wind speed < 1 m/s AND solar_zenith < 60° (diurnal warming risk)
   ```

2. **Diurnal Warming Correction (If Daytime Data Enabled)**
   ```
   correction = f(wind_speed, solar_radiation, time_of_day)

   Where:
   - Low winds → larger corrections
   - High winds → minimal corrections
   - Nighttime → no correction needed
   ```

3. **Uncertainty Weighting**
   ```
   observation_weight = base_weight * wind_factor

   Where:
   - wind_factor = 1.0 for moderate winds (3-10 m/s)
   - wind_factor = 0.5 for extreme winds (>15 m/s or <2 m/s)
   ```

**Implementation Requirements:**

```
1. ECMWF Data Access
   - Copernicus Climate Data Store (CDS) API
   - Download ERA5 hourly winds
   - Grid: 0.25° resolution (or 0.5° for efficiency)
   - Variables: u10, v10 (10-meter wind components)

2. Preprocessing Integration
   - Add wind field reader to preprocessing containers
   - Spatiotemporal interpolation to observation locations
   - Calculate wind speed: sqrt(u10^2 + v10^2)

3. Filtering Logic
   - Add wind-based QC flags to BIC/BIQ files
   - Implement in makebiq.m or l2p2bic.m
   - Configurable thresholds per sensor

4. Storage Requirements
   - ERA5 winds: ~50 MB/day compressed
   - Annual: ~18 GB
   - Modest compared to L2P data (~1.6 TB/year)
```

**Code References (Groundwork):**
- `makebiq` mentions "wind-dependent filtering" (not implemented)
- Infrastructure exists for additional QC flags in BIQ format

**Estimated Effort:** 3-6 months (data pipeline, interpolation, validation)

**Priority:** Low-Medium (quality improvement, prerequisite for daytime data)

**Challenges:**
- Data latency: ERA5 reanalysis has 5-day lag
- Could use ECMWF operational forecast for NRT (5-hour latency)
- Need to validate wind product quality against buoy winds

---

## REA Mode Full Implementation

### Current State: Partially Implemented

**Implementation Status:** ⚠️ Partially Implemented (Infrastructure Present)

**Current Status:**
- **NRT (Near Real-Time) Mode:** ✅ Fully operational
  - Uses previous day's L=6 coefficients as background
  - Fast processing for operational delivery
  - Optimizes for speed over completeness

- **REA (Reanalysis) Mode:** ⚠️ Partially implemented
  - Infrastructure exists (mode detection, parameter handling)
  - Preprocessing components support REA
  - **MRVA stage not yet containerized** (pending development)

**What Works:**
- Mode detection based on data age
- Stability latency logic for REA vs NRT
- Preprocessing respects REA requirements (no cache skipping)
- Configuration parameters for REA processing

**What's Missing:**

1. **MRVA Container for REA**
   - Current: MRVA not containerized
   - Needed: Containerized MRVA with REA mode support
   - Difference: REA starts from L=2 (coarse), NRT starts from L=6 (medium)

2. **Quality Assurance for REA**
   - Need validation against buoy/ship observations
   - Comparison with NRT products
   - Consistency checks across reprocessed periods

3. **Automated Reprocessing Workflows**
   - Systematic reanalysis for data corrections
   - Batch processing of historical periods
   - Gap filling for missed NRT days

**Implementation Requirements:**

```
1. MRVA Containerization
   - Port Fortran MRVA code to container
   - Support both NRT (L0=6) and REA (L0=2) modes
   - Parameter configuration via environment variables

2. REA Orchestration
   - Enhanced pipeline orchestrator
   - Multi-day batch processing
   - Resource management for long runs

3. Validation Pipeline
   - Compare REA vs NRT statistics
   - Validation against withheld observations
   - Long-term consistency checks

4. Documentation
   - REA-specific configuration guide
   - Best practices for reanalysis campaigns
   - Expected runtime and resource usage
```

**Estimated Effort:** 4-8 months (MRVA containerization, testing, validation)

**Priority:** High (enables reprocessing for data corrections and research)

---

## Additional Sensor Integration

### Sensors Considered but Not Yet Integrated

**Implementation Status:** ❌ Not Implemented

Several satellite sensors could enhance MUR coverage and quality:

### 1. VIIRS (Visible Infrared Imaging Radiometer Suite)

**Satellite:** NOAA-20, SNPP
**Type:** Infrared
**Resolution:** ~750m (similar to MODIS)
**Status:** Available from PO.DAAC

**Advantages:**
- Similar resolution to MODIS
- Additional temporal coverage
- Improved cloud detection

**Integration Path:**
- Add to `SensorTable.m` with La=2, Lb=12
- Similar processing to MODISA/MODIST
- Collection: `VIIRS_NPP-OSPO-L2P-v2.61`

### 2. GOES-R ABI (Geostationary)

**Satellite:** GOES-16/17 (West/East)
**Type:** Infrared (geostationary)
**Resolution:** ~2 km
**Coverage:** Americas only

**Advantages:**
- High temporal resolution (15 min)
- Excellent for diurnal studies (if daytime enabled)
- Cloud gap filling

**Challenges:**
- Regional coverage only
- Large data volume (many granules/day)
- Geostationary viewing angle effects

### 3. Himawari-8/9 AHI

**Satellite:** Himawari-8/9
**Type:** Infrared (geostationary)
**Resolution:** ~2 km
**Coverage:** Asia-Pacific

**Similar to GOES:** High temporal, regional coverage

### 4. SMAP SST

**Satellite:** Soil Moisture Active Passive
**Type:** Microwave (L-band)
**Resolution:** ~40 km
**Status:** Available

**Advantages:**
- All-weather like AMSR2
- Different frequency (complementary)

**Configuration:**
- Add with La=2, Lb=7 (coarse resolution)

**See:** [SENSOR_ADAPTATION.md](SENSOR_ADAPTATION.md) for integration procedures

---

## Processing Optimizations

### Potential Performance Improvements

**Implementation Status:** ❌ Not Implemented

### 1. GPU Acceleration for MRVA

**Current:** CPU-only PCG solver
**Proposed:** GPU-accelerated sparse linear algebra

**Potential Speedup:** 5-10x for solver stage

**Requirements:**
- CUDA/OpenCL implementation
- GPU-compatible MATLAB or Fortran libraries
- Testing on GPU-enabled infrastructure

### 2. Parallel L2P Processing

**Current:** Sequential sensor processing
**Proposed:** Parallel execution of multiple sensors

**Implementation:**
- Already possible with current containers
- Need orchestrator enhancement
- Resource management (memory, I/O)

**Speedup:** ~4x (processing 4 sensors in parallel)

### 3. Incremental Processing

**Current:** Full reprocessing each day
**Proposed:** Update only changed observations

**Concept:**
- Track which observations changed since last run
- Only reprocess affected scales
- Maintain coefficient continuity

**Complexity:** High (dependency tracking)
**Benefit:** Potentially 50% reduction in processing time

### 4. Cloud-Native Storage

**Current:** Local filesystem (/nas2)
**Proposed:** Object storage (S3, GCS)

**Advantages:**
- Scalable storage
- Redundancy
- Cost-effective archival
- Multi-region access

**Challenges:**
- I/O performance for random access
- Data transfer costs
- Need for caching layer

---

## Quality Control Enhancements

### Advanced QC Methods

**Implementation Status:** ❌ Not Implemented

### 1. Machine Learning-Based QC

**Concept:**
- Train ML model to detect anomalous observations
- Features: SST, location, time, sensor, neighboring obs
- Flag suspicious data before MRVA

**Potential Applications:**
- Cloud contamination detection
- Sensor calibration drift
- Frontal feature validation

### 2. Cross-Sensor Consistency Checks

**Current:** Basic range checks
**Proposed:** Inter-sensor validation

**Example:**
```
If MODIS and AMSR2 differ by >2°C at same location:
  - Flag as potential issue
  - Check other sensors
  - Downweight if inconsistent
```

### 3. Temporal Consistency

**Concept:**
- Check if SST change from previous day is reasonable
- Flag sudden jumps (>5°C/day) for review
- Useful for detecting sensor issues

### 4. Spatial Gradient Limits

**Current:** No explicit gradient constraints
**Proposed:** Flag extreme spatial gradients

**Rationale:**
- Real ocean fronts rarely exceed ~0.5°C/km
- Stronger gradients may indicate retrieval errors
- Could flag cloud edges, land contamination

---

## Implementation Priorities

### Recommended Phasing

**Phase 1 (High Priority, 6-12 months):**
1. ✅ Complete MRVA containerization
2. ✅ Full REA mode support
3. ⚠️ Basic quality assurance pipeline

**Phase 2 (Medium Priority, 12-18 months):**
1. ❌ VIIRS sensor integration
2. ❌ Parallel L2P processing optimization
3. ❌ Cross-sensor consistency checks

**Phase 3 (Lower Priority, 18-24 months):**
1. ❌ ECMWF wind integration (if daytime not pursued)
2. ❌ Geostationary sensors (GOES, Himawari)
3. ❌ GPU acceleration exploration

**Phase 4 (Research/Long-term):**
1. ❌ Daytime data processing (requires ECMWF)
2. ❌ Machine learning QC
3. ❌ Cloud-native architecture

---

## Decision Considerations

### Daytime Data: Proceed or Not?

**Arguments For:**
- 40-50% more observations
- Better coverage in cloudy regions
- Higher resolution temporal sampling

**Arguments Against:**
- Diurnal warming model complexity
- Additional dependencies (ECMWF winds)
- Risk to product quality if correction fails
- Nighttime-only is scientifically sound approach

**Recommendation:** Defer until REA mode is fully operational and validated. Then prototype daytime processing in research mode with extensive validation.

### ECMWF Wind: Independent Value?

**Without Daytime Processing:**
- Limited benefit (quality filtering only)
- Adds dependency and latency
- May not justify complexity

**With Daytime Processing:**
- Essential for diurnal warming correction
- Enables quality improvements
- Worth the implementation cost

**Recommendation:** Implement only if daytime data processing is pursued, or if specific quality issues emerge that wind filtering would address.

### REA Mode: Critical Path

**Why Important:**
- Enables reprocessing for data corrections
- Required for long-term climate record consistency
- Allows validation and improvement studies
- Supports research applications

**Recommendation:** Complete REA implementation before pursuing other enhancements. It's foundational for product quality and scientific credibility.

---

## References

### Scientific Literature

- **Diurnal Warming:**
  - Gentemann, C. L., et al. (2003). "Diurnal signals in satellite sea surface temperature measurements." *Geophysical Research Letters*, 30(3).
  - Fairall, C. W., et al. (1996). "Cool-skin and warm-layer effects on sea surface temperature." *Journal of Geophysical Research*, 101(C1), 1295-1308.

- **Foundation Temperature:**
  - Donlon, C. J., et al. (2002). "Toward improved validation of satellite sea surface skin temperature measurements for climate research." *Journal of Climate*, 15(4), 353-369.

- **MUR Algorithm:**
  - Chin, T. M., et al. (2017). "A multi-scale high-resolution analysis of global sea surface temperature." *Remote Sensing of Environment*, 200, 154-169.

### External Resources

- ECMWF ERA5: https://www.ecmwf.int/en/forecasts/datasets/reanalysis-datasets/era5
- PO.DAAC L2P Data: https://podaac.jpl.nasa.gov/
- GHRSST Science Team: https://www.ghrsst.org/

---

## Conclusion

This document captures enhancements that have been considered for the MUR system. While some features have preliminary groundwork in the codebase (daytime filtering hooks, REA mode infrastructure), they should not be considered operational.

**Key Takeaways:**

1. **Current system is nighttime-only** - This is scientifically sound and avoids diurnal complications
2. **REA mode exists in infrastructure** - But MRVA containerization needed for full implementation
3. **Daytime + ECMWF are coupled decisions** - Don't implement one without the other
4. **Focus on fundamentals first** - Complete REA mode before pursuing advanced features

Future development should prioritize product quality and operational stability over coverage expansion or algorithmic complexity.

---

*Last Updated: 2025-01-19*
*Status: Planning Document - Features Not Implemented*
