# mur

The NASA Physical Oceanography Distributed Active Archive Center (PO.DAAC) Multi-scale Ultra-high Resolution (MUR) and MUR Reanalysis and Validation for Applications (MRVA) programs aim to deliver high-resolution sea surface temperature (SST) products to support Earth system science, weather forecasting, climate research, and decision-making across ocean, coastal, and polar domains.

The MUR workflow is made up of several components:

1) Input: Landmask & Ice, IQUAM Buoy (In Situ), Level 2P Satellite Sensors
2) Processing: MRVA
3) Output (Aggregates results and uploads to S3)

## Documentation

**Everything is on the documentation site: <https://podaac.github.io/mur/>** —
an overview of the system, a quick start, how the multi-scale analysis works,
the full configuration and input-contract references, per-container command
lines, and the MRVA internals. It is published from [`docs/`](docs/) via GitHub
Pages, and it is the documentation: there is no second Markdown copy to fall
out of date.

Where to start:

- **[Overview](https://podaac.github.io/mur/)** - what MUR is and how the pipeline fits together
- **[Quick start](https://podaac.github.io/mur/quickstart.html)** - build the images and process a day
- **[Architecture](https://podaac.github.io/mur/architecture.html)** - the four containers and the contract they follow
- **[The MRVA algorithm](https://podaac.github.io/mur/algorithm.html)** - multi-scale variational analysis, in depth
- **[Data lifecycle](https://podaac.github.io/mur/lifecycle.html)** - sources, windows, caching and storage
- **[Daily execution](https://podaac.github.io/mur/sequence.html)** - what a scheduled run does, NRT versus reanalysis
- **[Configuration](https://podaac.github.io/mur/configuration.html)** - every key in `config.json`, and troubleshooting
- **[Static input data](https://podaac.github.io/mur/static-data.html)** - the reference files you must stage yourself
- **[Input contract](https://podaac.github.io/mur/input-contract.html)** - the named-flag and manifest schema
- **[Adding a sensor](https://podaac.github.io/mur/sensors.html)** - integrating a new L2P instrument
- **[Running on MAAP](https://podaac.github.io/mur/maap.html)** - cloud execution, and how far it is wired up
- **[MRVA internals](https://podaac.github.io/mur/mrva-internals.html)** - the MATLAB and Fortran implementation

**Per-container reference:**

- [Land/ice](https://podaac.github.io/mur/container-landice.html)
- [L2P satellite processing](https://podaac.github.io/mur/container-l2p.html)
- [iQUAM buoy processing](https://podaac.github.io/mur/container-iquam.html)
- [MRVA analysis](https://podaac.github.io/mur/container-mrva.html)
- [Data viewer](dataviewer/README.md)
- [MATLAB base image](matlab-base/README.md)

## Quick Start

### Prerequisites

- [Docker](#docker-setup-guide) (see setup guide below)
- [uv](https://docs.astral.sh/uv/) - Python package manager

### Environment Setup

Install dependencies and create the uv environment:

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync environment (creates .venv and installs all dependencies)
cd mur
uv sync

# Activate the environment (optional - uv handles this automatically)
source .venv/bin/activate

# This setup creates convenient command shortcuts when the venv is active:
#   mur-pipeline  - Pipeline orchestrator (replaces: uv run run_mur_pipeline.py)
#   mur-viewer    - Data file viewer (replaces: uv run dataviewer/dataviewer.py)
#
# You can use these commands directly if the venv is active,
# or prefix with 'uv run' without activating:
#   uv run mur-pipeline --config config.json
```

### Building Containers

`./build_module.sh` is the supported way to build every processing container. Run it from the `mur/` directory:

```bash
# Build all modules (iquam, l2p, landice, mrva)
./build_module.sh all

# Build a single module
./build_module.sh mrva

# Build with debug symbols and bounds checking
./build_module.sh mrva --debug

# Force rebuild without Docker cache
./build_module.sh all --no-cache
```

The script builds the `mur-matlab-base:r2024b` image first if it is missing, verifies `network.lic` exists, always builds `--platform linux/amd64` with the parent `mur/` directory as build context, and tags the result `mur-iquam:latest`, `mur-l2p:latest`, `mur-landice:latest`, or `mur-mrva:latest` — the exact names the pipeline config (`config.json`) expects.

Prerequisite: copy `network.lic.example` to `network.lic` and point it at your MATLAB license server before the first build.

For raw `docker build` invocations (CI images, one-off experiments, debugging the Dockerfiles themselves), see [Manual builds (advanced)](https://podaac.github.io/mur/configuration.html#manual-builds-advanced). See [MATLAB Base Image](matlab-base/README.md) for base image details.

### Production-Style Pipeline Orchestrator

A production-style test orchestrator is available that mimics the architecture of `nrtMRVA.py`:

```bash
# Run for yesterday's data (NRT mode) -- landice, iquam, l2p, and mrva
mur-pipeline --config config.json
# or: uv run run_mur_pipeline.py --config config.json

# Run full 9-day window (REA + NRT modes)
mur-pipeline --config config.json --all-stages

# Run for specific date
mur-pipeline --config config.json --date 2024-08-08

# Preprocessing only (landice, iquam, l2p), skip MRVA
mur-pipeline --config config.json --all-stages --preprocess-only
```

**L2P downloading is a separate stage, not run by default** — `l2p` only turns already-downloaded granules into BIC files; nothing downloads unless you run `--execute l2p-download` explicitly (normally via cron: `run_l2p_download_cron.sh`/`run_l2p_deepsync_cron.sh` at the repo root). See [Configuration](https://podaac.github.io/mur/configuration.html) for the full command-line reference.

**Key Features:**

- **Explicit-args containers**: every input (static files, per-day outputs, sensor fan-in) is a named flag, resolved by the Python orchestrator — never a bind-mounted directory the container scans
- **Local or S3, uniformly**: the same flags accept either a local path or an `s3://` href
- **NRT vs REA modes**: Automatic mode detection based on data age
- **Stability latency**: Smart reprocessing only when data changes
- **All four stages operational**: landice, iquam, l2p, and mrva all produce real output

See [run_mur_pipeline.py](run_mur_pipeline.py) and [Configuration](https://podaac.github.io/mur/configuration.html) for full details.

## InputGen Operations

This component creates coordinating JSON files that can be used by execution infrastructure to execute the MUR algorithms in parallel.

See this README for details: [InputGen README](inputgen/README.md)

## Land Ice Operations

This component prepares landmask and sea ice boundary data used in downstream MUR processing. It generates and runs MATLAB scripts that apply land and ice masking operations to MUR SST inputs for the previous 9 days. Two grid resolutions (`p01` at 0.01° and `p011` at 0.011°) are supported. It is parallelized on the day which are arguments to the script. The InputGen operations produce the required date ranges to execute on.

See the [land/ice container reference](https://podaac.github.io/mur/container-landice.html) for details.

## iQUAM Buoy Operations

This component downloads and processes in-situ buoy observations from the iQUAM (in situ Quality Monitor) dataset. These observations provide ground truth SST measurements used for bias correction and validation in the MRVA analysis.

See the [iQUAM container reference](https://podaac.github.io/mur/container-iquam.html) for details.

## L2P Sensor Operations

This component downloads (or loads) L2P Sensor data from Earthdata and combines the data in to a binary file to be read by the MRVA process. It is parallelized on the sensor and day which are arguments to the script. The InputGen operations produce the required sensor and date ranges to execute on.

See the [L2P container reference](https://podaac.github.io/mur/container-l2p.html) for details.

## MRVA Processing

The Multi-Resolution Variational Analysis (MRVA) is the core algorithm that combines all input data sources (land/ice masks, buoy observations, and satellite SST) to produce the final MUR SST product through multi-scale optimal interpolation.

See the [MRVA container reference](https://podaac.github.io/mur/container-mrva.html) for details.

## Docker Setup Guide

This guide explains how to install Docker **without Docker Desktop** on macOS and Windows.

> **Why not Docker Desktop?** Docker Desktop requires a paid license for commercial use in organizations with more than 250 employees or more than $10 million in revenue. The alternatives below are free and often perform better.

---

### macOS Setup (Colima)

[Colima](https://github.com/abiosoft/colima) is a lightweight Docker runtime for macOS that uses either Apple's native Virtualization.Framework or QEMU.

#### Install Homebrew

Install [Homebrew](https://brew.sh/) if you haven't already:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

#### Step 1: Install Docker CLI and Colima

```bash
brew install docker docker-credential-helper
brew install colima
```

#### Step 2: Configure Docker Credentials

Create or edit `~/.docker/config.json`:

```bash
mkdir -p ~/.docker
cat > ~/.docker/config.json << 'EOF'
{
    "auths": {},
    "credsStore": "osxkeychain",
    "currentContext": "colima"
}
EOF
```

#### Step 3: Start Colima with Apple Virtualization (Recommended)

For **Apple Silicon Macs (M1/M2/M3/M4)** running macOS 13+:

```bash
colima start --vm-type vz --vz-rosetta --mount-type virtiofs --cpu 4 --memory 8
```

For **Intel Macs** running macOS 13+:

```bash
colima start --vm-type vz --mount-type virtiofs --cpu 4 --memory 8
```

**Configuration options explained:**

| Option | Description |
| ------ | ----------- |
| `--vm-type vz` | Uses Apple's native Virtualization.Framework (requires macOS 13+) |
| `--vz-rosetta` | Enables Rosetta 2 for x86_64 emulation on Apple Silicon |
| `--mount-type virtiofs` | Uses virtiofs for faster file sharing between host and VM |
| `--cpu 4` | Allocates 4 CPU cores to the VM (adjust based on your machine) |
| `--memory 8` | Allocates 8GB of RAM to the VM (adjust based on your needs) |

#### Step 4: Verify Installation

```bash
# Check colima status
colima status

# Verify docker is working
docker version
docker run hello-world
```

You should see output like:

```text
INFO[0000] colima is running using macOS Virtualization.Framework
INFO[0000] arch: aarch64
INFO[0000] runtime: docker
INFO[0000] mountType: virtiofs
```

#### Performance Benefits of Apple Virtualization

Using `--vm-type vz` with `--mount-type virtiofs` provides significant performance improvements over QEMU:

- Build times can be reduced by up to 80% compared to QEMU
- File I/O operations are much faster with virtiofs
- Lower CPU overhead from native virtualization

#### Managing Colima

```bash
# Start colima (uses previous configuration)
colima start

# Stop colima
colima stop

# Delete colima VM (to reconfigure)
colima delete

# Check status
colima status
```

#### Fallback: QEMU (macOS 12 or earlier)

If you're on macOS 12 or earlier, or need QEMU for compatibility:

```bash
# Basic QEMU configuration
colima start --cpu 4 --memory 8

# QEMU with Rosetta for x86 emulation on Apple Silicon
colima start --arch x86_64 --cpu 4 --memory 8
```

#### Troubleshooting macOS

**Docker context not set:**

```bash
docker context use colima
```

**Permission denied errors:**

```bash
# Ensure colima is running
colima status

# If needed, restart
colima stop && colima start
```

**Slow file operations:**
Make sure you're using `--mount-type virtiofs` (requires `--vm-type vz`).

For more help, see the [Colima FAQ](https://github.com/abiosoft/colima/blob/main/docs/FAQ.md).

---

### Windows Setup (WSL2 + Docker Engine)

On Windows, you can run Docker Engine inside WSL2 (Windows Subsystem for Linux) without Docker Desktop.

#### Requirements

- Windows 10 version 2004+ or Windows 11
- Administrator access

#### Step 1: Enable WSL2

Open PowerShell as Administrator and run:

```powershell
# Enable WSL
wsl --install

# Restart your computer when prompted
```

After restart, set WSL2 as default:

```powershell
wsl --set-default-version 2
```

#### Step 2: Install a Linux Distribution

```powershell
# Install Ubuntu (recommended)
wsl --install -d Ubuntu

# Or list available distributions
wsl --list --online
```

Launch Ubuntu from the Start menu and complete the initial setup (create username/password).

#### Step 3: Install Docker Engine in WSL2

Inside your WSL2 Ubuntu terminal:

```bash
# Update packages
sudo apt-get update
sudo apt-get upgrade -y

# Install prerequisites
sudo apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Add Docker's official GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to the docker group (avoids needing sudo)
sudo usermod -aG docker $USER
```

#### Step 4: Configure Docker to Start Automatically

Create a script to start Docker when WSL launches:

```bash
# Add to ~/.bashrc or ~/.profile
echo '
# Start Docker daemon if not running
if ! pgrep -x "dockerd" > /dev/null; then
    sudo dockerd > /dev/null 2>&1 &
    sleep 2
fi
' >> ~/.bashrc
```

To avoid password prompts for starting Docker, add to sudoers:

```bash
sudo visudo
```

Add this line at the end:

```text
%docker ALL=(ALL) NOPASSWD: /usr/bin/dockerd
```

#### Step 5: Verify Installation

Close and reopen your WSL terminal, then:

```bash
# Check Docker is running
docker version

# Test with hello-world
docker run hello-world
```

#### Using Docker from Windows

You can access Docker from Windows PowerShell/CMD by installing the Docker CLI:

```powershell
# Using winget
winget install Docker.DockerCLI

# Or download from https://download.docker.com/win/static/stable/x86_64/
```

Then configure it to use the WSL2 Docker:

```powershell
# In PowerShell, set the Docker host to WSL
$env:DOCKER_HOST = "unix:///mnt/wsl/shared-docker/docker.sock"
```

Or add to your PowerShell profile for persistence.

#### Troubleshooting Windows

**WSL2 not available:**

```powershell
# Enable required Windows features
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
# Restart computer
```

**Docker daemon won't start:**

```bash
# Check for errors
sudo dockerd

# Common fix: remove old socket
sudo rm /var/run/docker.sock
sudo dockerd
```

**Permission denied:**

```bash
# Make sure you're in the docker group
groups
# Should include 'docker'

# If not, re-add and restart WSL
sudo usermod -aG docker $USER
# Then close all WSL windows and run: wsl --shutdown
```

---

### Logging into JPL Artifactory

Once Docker is set up, you can pull images from the JPL Artifactory:

```bash
docker login artifactory.jpl.nasa.gov
```

Enter your JPL username and Artifactory API token when prompted.

---

### Docker Quick Reference

| Task | macOS (Colima) | Windows (WSL2) |
| ---- | -------------- | -------------- |
| Start Docker | `colima start` | (auto-starts with WSL) |
| Stop Docker | `colima stop` | `sudo service docker stop` |
| Check status | `colima status` | `sudo service docker status` |
| View logs | `colima logs` | `journalctl -u docker` |

## CalTech Copyright

Copyright [2025], by the California Institute of Technology. ALL RIGHTS RESERVED. United States Government Sponsorship acknowledged. Any commercial use must be negotiated with the Office of Technology Transfer at the California Institute of Technology.

This software may be subject to U.S. export control laws. By accepting this software, the user agrees to comply with all applicable U.S. export laws and regulations. User has the responsibility to obtain export licenses, or other export authority as may be required before exporting such information to foreign countries or providing access to foreign persons.
