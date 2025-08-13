# MUR L2P Sensor Operations

This script executes **MUR (Multi-scale Ultra-high Resolution)** L2P (Level 2 Preprocessed) sensor operations for a given sensor, day of year, and year.

It handles downloading input data, preparing MATLAB scripts for processing, running the MATLAB commands, and cleaning up downloaded files.

## Overview

The script:
1. Parses arguments for sensor, date, input/output directories, and configuration.
2. Optionally downloads L2P data for the given date via HTTP or S3 access.
3. Creates a MATLAB `.m` command file from a template with the correct parameters.
4. Executes MATLAB to process the downloaded data.
5. Cleans up intermediate files after processing.

## Requirements

- Python 3.12+
- MATLAB R2021b+ or compatible version (path configurable in script)
- External tools and templates:
  - `podaac-data-downloader` binary
  - `l2p_template.m` MATLAB template file
- Python dependencies:
  - `argparse` (standard library)
  - `datetime` (standard library)
  - `json` (standard library)
  - `logging` (standard library)
  - `os` (standard library)
  - `pathlib` (standard library)
  - `subprocess` (standard library)
  - `earthaccess`
  - `fsspec`

## Docker Build and Run Instructions

### .netrc Setup

The `.netrc` file is required for authenticating with NASA Earthdata.

1. Create a `.netrc` file in your home directory:
    ```bash
    touch ~/.netrc
    chmod 600 ~/.netrc
    ```
2. Add your Earthdata credentials:
    ```
    machine urs.earthdata.nasa.gov
        login <your-username>
        password <your-password>
    ```

### Build the image

From the repository root:

```
docker build -t mur-l2p:latest .
```

If you need to provide a .netrc file during build (as a Docker secret):

```
DOCKER_BUILDKIT=1 docker build \
  --secret id=netrc_file,src=$HOME/.netrc \
  -t mur-l2p:latest .
```

### Run the container

Mount your input/output directories and .netrc:

  ```
  docker run --rm \
    -v /path/to/input:/data/input \
    -v /path/to/output:/data/output \
    -v $HOME/.netrc:/home/matlab/.netrc:ro \
    mur-l2p:latest \
      -s AMSR2R \
      -d 220 \
      -y 2025 \
      -i /data/input \
      -o /data/output \
      -c /data/input/config.json \
      -w
  ```

If using the Docker secret method, you can mount the .netrc at runtime like this:

  ```
  docker run --rm \
    --mount type=secret,id=netrc_file,target=/home/matlab/.netrc \
    -v /path/to/input:/data/input \
    -v /path/to/output:/data/output \
    mur-l2p:latest \
    python execute_l2p.py ...
```

## Usage

```bash
python execute_l2p.py \
  -s AMSR2R \
  -d 220 \
  -y 2025 \
  -i /path/to/input/data \
  -o /path/to/output/data \
  -c /path/to/config.json \
  -w
```

# Test L2P execution

This script runs **the L2P algorithm** in the MUR (Multi-scale Ultra-high Resolution) workflow.

It is primarily intended for **testing execution** against coordinated input files and demonstrating **parallelization** in the workflow.


## Features

- Executes **L2P algorithm** using configuration-based parameters.
- Supports **parallel processing** with a configurable CPU count (`CPU_COUNT` constant in script).
- Logs execution details including runtime and parameter values.
- Example for **integrating parallelism** into a workflow.

## Requirements

- Python 3.8+
- Standard library only — no additional dependencies.
- Access to the L2P algorithm script referenced in the config.

## Configuration File

The configuration file (`config.json`) must include:

```json
{
    "python_exe": "/path/to/python",
    "script": "/path/to/l2p_script.py",
    "input": "/path/to/input/data",
    "output": "/path/to/output/data",
    "config": "/path/to/l2p_config.json",
    "inputgen_data": "/path/to/l2p_inputgen.json"
}
