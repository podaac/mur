# mur

The NASA Physical Oceanography Distributed Active Archive Center (PO.DAAC) Multi-scale Ultra-high Resolution (MUR) and MUR Reanalysis and Validation for Applications (MRVA) programs aim to deliver high-resolution sea surface temperature (SST) products to support Earth system science, weather forecasting, climate research, and decision-making across ocean, coastal, and polar domains.

The MUR workflow is made up of several components:

1) Input: Landmask & Ice, IQUAM Buoy (In Situ), Level 2P Satellite Sensors
2) Processing: MRVA
3) Output (Aggregates results and uploads to S3)

## InputGen Operations

This component creates coordinating JSON files that can be used by exectuion infrastructure to execute the MUR algorithms in parallel.

See this README for details: [InputGen README](inputgen/README.md)

## Land Ice Operations

This component prepares landmask and sea ice boundary data used in downstream MUR processing. It generates and runs MATLAB scripts that apply land and ice masking operations to MUR SST inputs for the previous 9 days. Two grid resolutions (`p01`, `p11`) are supported.

See this README for details: [Land Ice README](landice/README.md)

## L2P Sensor Operations

This component downloads (or loads) L2P Sensor data from Earthdata and combines the data in to a binary file to be read by the MRVA process. It is parallelized on the sensor and day which are arguments to the script. The InputGen operations produce the required sensor and date ranges to execute on.

See this README for details: [L2P README](l2p/README.md)
