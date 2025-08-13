# MUR L2P Coordination Data Generator

This script generates the JSON file needed to coordinate the execution of MUR (Multi-scale Ultra-high Resolution) algorithms.

Specifically, it produces a `l2p.json` file containing date ranges for each sensor, based on a configuration file.

## Overview

The script:
1. Reads a configuration file defining sensors and their date ranges.
2. Calculates the date ranges for each sensor based on the current date and the specified day range.
3. Writes the result to `l2p.json` in the specified output directory.

This output can then be used to coordinate and schedule MUR processing workflows.

---

## Requirements

- The following Python packages:
  - `argparse` (standard library)
  - `datetime` (standard library)
  - `json` (standard library)
  - `logging` (standard library)
  - `pathlib` (standard library)
  - `fsspec` (only required if configuration file is stored on S3)

---

## Usage

```bash
python generate_l2p.py -o /path/to/output/dir -c /path/to/config.json
