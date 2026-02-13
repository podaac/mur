# mur

The NASA Physical Oceanography Distributed Active Archive Center (PO.DAAC) Multi-scale Ultra-high Resolution (MUR) and MUR Reanalysis and Validation for Applications (MRVA) programs aim to deliver high-resolution sea surface temperature (SST) products to support Earth system science, weather forecasting, climate research, and decision-making across ocean, coastal, and polar domains.

The MUR workflow is made up of several components:

1) Input: Landmask & Ice, IQUAM Buoy (In Situ), Level 2P Satellite Sensors
2) Processing: MRVA
3) Output (Aggregates results and uploads to S3)

## InputGen Operations

This component creates coordinating JSON files that can be used by exectuion infrastructure to execute the MUR algorithms in parallel.

Runtime: 2025-08-13T20:55:10,308 root INFO Execution time: 0:02:29.569614

See this README for details: [InputGen README](inputgen/README.md)

## Land Ice Operations

This component prepares landmask and sea ice boundary data used in downstream MUR processing. It generates and runs MATLAB scripts that apply land and ice masking operations to MUR SST inputs for the previous 9 days. Two grid resolutions (`p01`, `p11`) are supported. It is parallelized on the day which are arguments to the script. The InputGen operations produce the required date ranges to execute on.

See this README for details: [Land Ice README](landice/README.md)

## L2P Sensor Operations

This component downloads (or loads) L2P Sensor data from Earthdata and combines the data in to a binary file to be read by the MRVA process. It is parallelized on the sensor and day which are arguments to the script. The InputGen operations produce the required sensor and date ranges to execute on.

Runtime: 2025-08-13T20:27:57,501 root INFO Execution time: 0:32:30.754806 (fully parallelized )

See this README for details: [L2P README](l2p/README.md)

## CalTech Copyright
Copyright [2025], by the California Institute of Technology. ALL RIGHTS RESERVED. United States Government Sponsorship acknowledged. Any commercial use must be negotiated with the Office of Technology Transfer at the California Institute of Technology.
 
This software may be subject to U.S. export control laws. By accepting this software, the user agrees to comply with all applicable U.S. export laws and regulations. User has the responsibility to obtain export licenses, or other export authority as may be required before exporting such information to foreign countries or providing access to foreign persons.
