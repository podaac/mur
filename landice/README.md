# Land Ice Operations Execution Script

This script automates the generation and execution of MATLAB scripts used for applying landmask and ice operations to MUR SST input data. It creates and runs MATLAB files for a range of recent dates, preparing data for two grid resolutions (`p01` and `p11`) using the OSI SAF sea ice datasets.

---

## Overview

The script:
- Iterates over the last **9 days** of data.
- Creates MATLAB `.m` execution files from a template (`landice_template.m`).
- Sets necessary environment variables for MATLAB to access OSI SAF FTP endpoints.
- Executes the `.m` scripts using MATLAB in batch mode.
- Parallelized by day (with InputGen providing date ranges).

---

## Requirements

- Python 3.9+
- MATLAB (default path: `/opt/matlab/R2021b/bin/matlab`)
- `landice_template.m` must be present in the current working directory.
- Input data must be available in the specified input directory.

---

## Setup

### 1. Prepare directories

Ensure input data is available in a local or mounted directory and that an output directory exists for the results.

Example:

```
/home/username/mur/data/landice/input
/home/username/mur/data/landice/output
```

---

## Usage

### Run locally with Python

```bash
python3 execute_landice.py \
  -i /home/username/mur/data/landice/input \
  -o /home/username/mur/data/landice/output \
  -y 2025 \
  -d 225
```

This command:

- Sets up the OSISAF FTP paths as environment variables.
- Iterates over the last 9 days.
- Generates and runs a MATLAB .m script for each day and resolution (p01, p11).

### Docker Usage

Assuming you’ve built a Docker image named landice, run:

```bash
docker run --rm --name landice \
  -v /home/ec2-user/data:/mnt/data \
  landice \
  -i /mnt/data/input \
  -o /mnt/data/output \
  -y 2025 \
  -d 225
```

This command:

- Mounts your local data directory into the container.
- Runs the same land ice processing logic inside the container.

---

## MATLAB Execution Details

For each date and resolution, a file like the following is generated: `makeice_2025_187_p01.m`

It requires environment setup:

```bash
setenv OSISAF_FTP_REPROCESSED ftp://osisaf.met.no/reprocessed/ice/conc/v1p2
setenv OSISAF_FTP_ARCHIVE ftp://osisaf.met.no/archive/ice/conc
setenv OSISAF_FTP_PROD ftp://osisaf.met.no/prod/ice/conc
```

And is executed using: `/opt/matlab/R2021b/bin/matlab -nodisplay < makeice_2025_187_p01.m`

Notes

- You can optionally delete generated .m files after execution (see the commented unlink() line in the script).
- The script logs key steps and execution time to aid in monitoring and debugging.
