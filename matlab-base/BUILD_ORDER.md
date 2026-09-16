# Build Order and Usage Guide

## Overview

The MUR processing system now uses a shared MATLAB base image to avoid redundant downloads and installations. This significantly reduces build time and disk space.

## Build Order

### 1. Build the Base Image (First Time Only)

```bash
cd /path/to/mur
cp network.lic.example network.lic  # Edit with your license server details
./build_matlab_base.sh
```

This creates the `mur-matlab-base:r2024b` image (~3.5GB) with:
- MATLAB R2024b Runtime installed at `/opt/matlabruntime/R2024b`
- Common runtime dependencies (libc6, libstdc++6, zlib1g, etc.)
- Standard MATLAB environment variables

The base image build takes **10-20 minutes** on first run but only needs to be built once.

### 2. Build Individual Modules

After the base image exists, build any module:

```bash
# Build a specific module
./build_module.sh iquam
./build_module.sh l2p
./build_module.sh landice
./build_module.sh mrva

# Or build all modules at once
./build_module.sh all
```

The build script automatically:
1. Checks if the base image exists
2. Builds the base image if needed
3. Builds the requested module(s)

## Benefits of This Approach

### Before (Separate Downloads)
- Each module downloaded ~2GB MATLAB runtime
- 4 modules = ~8GB downloads + installation time
- No caching between modules
- Wasted network bandwidth on rebuilds

### After (Shared Base Image)
- Base image downloads runtime once: ~2GB
- All modules reuse the same base: **0 additional downloads**
- Docker caches the base image layers
- Rebuilding modules is much faster

### Time Savings
- **First build**: ~10 minutes for base + ~5 minutes per module
- **Subsequent module builds**: ~5 minutes each (no runtime download/install)
- **Rebuilding after code changes**: ~2-3 minutes (MATLAB compilation only)

### Disk Space Savings
- Before: 4 separate runtime installations = ~14GB
- After: 1 shared base layer = ~3.5GB
- **Savings: ~10.5GB**

## Manual Builds (Advanced)

`build_matlab_base.sh` / `build_module.sh` are the supported path. Build by hand only when
you need something they don't do — a custom tag, an external CI system, or debugging a
Dockerfile. Note the `mur-` prefixed tags: the pipeline's `config.json` looks for exactly
these names.

```bash
# Build base image
cd mur/matlab-base
docker build --platform linux/amd64 -t mur-matlab-base:r2024b -f Dockerfile ..

# Build individual modules
cd mur/iquam
docker build --platform linux/amd64 -t mur-iquam:latest -f Dockerfile ..

cd mur/l2p
docker build --platform linux/amd64 -t mur-l2p:latest -f Dockerfile ..

cd mur/landice
docker build --platform linux/amd64 -t mur-landice:latest -f Dockerfile ..

cd mur/mrva
docker build --platform linux/amd64 -t mur-mrva:latest -f Dockerfile ..
```

## Rebuilding the Base Image

If you need to update the MATLAB runtime version or rebuild the base image:

```bash
./build_matlab_base.sh --force
```

Then rebuild all modules to use the updated base:

```bash
./build_module.sh all
```

## Troubleshooting

### "Base image not found" during module build

The build script should automatically build the base image. If it doesn't:
```bash
./build_matlab_base.sh
```

### License errors during base build

Ensure `network.lic` has the correct license server details:
```bash
cat network.lic
# Should show SERVER and USE_SERVER lines with your license server
```

### Module compilation fails

This is a MATLAB compilation error (not base image related). Check:
- License server is accessible during build
- MATLAB source files are valid
- Check the specific error in the build output

## Architecture

```
┌─────────────────────────────────┐
│  mathworks/matlab:r2024b        │  (15GB - only used during builds)
└────────────┬────────────────────┘
             │
             ├──> Build MATLAB code (builder stage)
             │
             v
┌─────────────────────────────────┐
│  mur-matlab-base:r2024b         │  (3.5GB - shared by all modules)
│  - MATLAB Runtime R2024b        │
│  - Common dependencies          │
└────────────┬────────────────────┘
             │
             ├──> mur-iquam:latest    (runtime + iquam binaries)
             ├──> mur-l2p:latest      (runtime + l2p binaries)
             ├──> mur-landice:latest  (runtime + landice binaries)
             └──> mur-mrva:latest     (runtime + mrva binaries + fortran)
```

## What Changed in the Dockerfiles

Each module's Dockerfile was updated:

### Removed
- MATLAB Runtime download (was lines 68-141 in each)
- Custom runtime installer creation
- Runtime installation steps

### Changed
- Stage 2 now starts with `FROM mur-matlab-base:r2024b` instead of `FROM debian:bookworm-slim`
- Compilation no longer creates custom installer (simpler build command)

### Result
- Faster builds
- Smaller total disk usage
- Better layer caching
