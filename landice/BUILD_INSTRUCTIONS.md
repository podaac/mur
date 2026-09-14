# MATLAB R2024b LandIce Container Build Instructions

## Quick Start (Recommended)

Build with `build_module.sh` from the `mur/` directory. It builds the
`mur-matlab-base:r2024b` image if missing, checks `network.lic`, sets
`--platform linux/amd64`, uses the parent `mur/` directory as build context (so the
Dockerfile can reach `common/`), and tags the image `mur-landice:latest`:

```bash
cd mur
./build_module.sh landice
```

Run it (see [README.md](README.md) for the full named-flag invocation):

```bash
docker run --rm --shm-size=512M \
  -v /path/to/static-resources:/input:ro \
  -v /path/to/output:/output \
  mur-landice:latest \
  --year 2024 --doy 100 ...
```

For a raw `docker build` — custom tags, external CI, Dockerfile debugging — see
[Manual Builds (Advanced)](../documentation/PIPELINE_CONFIGURATION.md#manual-builds-advanced):

```bash
cd mur/landice
docker build --platform linux/amd64 -f Dockerfile -t mur-landice:latest ..
```

## Manual Compilation Process (Advanced)

The rest of this document covers compiling the MATLAB application **by hand inside a
development container** — useful when debugging `mcc` dependency problems or toolbox
requirements, not part of the normal build path. The single `landice/Dockerfile` does all
of this automatically; the `Dockerfile.matlab` / `Dockerfile.runtime` split described below
is historical, so adapt the commands to the current Dockerfile's builder stage.

## Prerequisites
- Docker installed on your system
- Access to MATLAB license server
- Network connectivity to download MATLAB toolboxes

Find the required toolboxes with

```matlab

[files, products] = matlab.codetools.requiredFilesAndProducts('myScript.m');

% Display required toolboxes
for i = 1:length(products)
    fprintf('Required: %s\n', products(i).Name);
end

```


## Building the MATLAB Development Container

### 1. Build the Docker Image

**Note:** `Dockerfile.matlab` no longer exists. The equivalent today is the builder stage of
`landice/Dockerfile`, or the shared base image `mur-matlab-base:r2024b` built by
`./build_matlab_base.sh`. Either gives you MATLAB R2024b + Compiler with `common/` available:

```bash
# Build the shared MATLAB base image (from mur/)
cd mur
./build_matlab_base.sh

# Or stop the landice build at its builder stage
cd mur/landice
docker build --platform linux/amd64 --target builder -t matlab-landice:r2024b -f Dockerfile ..
```

Both build with the parent `mur` directory as context, which is what lets the Dockerfile reach `landice/` and `common/`. Substitute whichever image you built for `matlab-landice:r2024b` in the commands below.

### 2. Run Interactive Terminal Session

```bash
# Run container with volume mounting
# Builds to /tmp inside container to avoid permission issues
docker run -it --rm \
  -v $(pwd):/app/landice \
  matlab-landice:r2024b
```

Note: 
- Container runs as the `matlab` user (not root) to comply with license server restrictions
- Build process uses `/tmp` to avoid volume mount permission issues

### 3. Build the LandIce Application Inside Container

Once inside the container terminal:

```bash
# Navigate to the landice directory
cd /app/landice

# Method 1: Build to temp location and copy back (recommended)
# This avoids volume mount permission issues
# -C flag creates separate CTF file for faster runtime extraction
mkdir -p /tmp/landice_build
mcc -m src/landice_wrapper.m \
    -a src/makeicefiles.m \
    -a src/readosisafice.m \
    -a src/setup_environment.m \
    -a src/julian.m \
    -o LandIce \
    -d /tmp/landice_build \
    -C \
    -R -nodisplay \
    -R -nosplash

# Copy the compiled files back to the mounted volume
cp -R /tmp/landice_build/LandIce ./build
```

Alternative methods:

```bash
# Method 2: Auto-detect dependencies (build to temp and copy)
mkdir -p /tmp/landice_build
mcc -m -v -d /tmp/landice_build -o LandIce src/landice_wrapper.m
mkdir -p ./build && cp /tmp/landice_build/* ./build/

# Method 3: Interactive MATLAB (if needed for debugging)
matlab -nodisplay -nosplash
# In MATLAB:
# >> mcc -m src/landice_wrapper.m -a src/makeicefiles.m -a src/readosisafice.m -a src/setup_environment.m -a src/julian.m -o LandIce -d /tmp/landice_build
# >> exit
# Then copy files: cp /tmp/landice_build/* ./build/
```

**Notes**:
- Building to `/tmp/landice_build` avoids volume mount permission issues completely
- The `-m` flag creates a standalone executable binary (not an installer)
- The `-C` flag creates a separate CTF archive for faster runtime extraction
- The `-n` flag automatically treats numeric command line arguments as MATLAB doubles (solves string conversion issues)
- The resulting executable only requires MATLAB Runtime R2024b, not full MATLAB
- The `-v` flag provides verbose output for troubleshooting
- MATLAB R2015b+ automatically finds dependencies, so `-a` for each file may not be necessary
- Files are copied back to `./build/` which is accessible from the host system

**Output Files**:
The compilation will produce:
- `LandIce` - The standalone executable binary (no installer)
- `LandIce.ctf` - Separate CTF (Component Technology File) archive for faster runtime extraction
- `run_LandIce.sh` - Shell script wrapper that sets up environment variables
- `readme.txt` - Runtime requirements and deployment instructions
- `requiredMCRProducts.txt` - List of required MATLAB Runtime components

## Running the Compiled Executable

### Direct Execution (with MATLAB Runtime installed)
```bash
# Using the wrapper script (recommended - handles environment setup)
# MCR path may vary by installation - check your system
./build/run_LandIce.sh /usr/local/MATLAB/MATLAB_Runtime/R2024b input_dir /path/to/input output_dir /path/to/output year 2024 doy 100

# Alternative common MCR paths:
./build/run_LandIce.sh /opt/mcr/R2024b input_dir /path/to/input output_dir /path/to/output year 2024 doy 100

# Or directly (requires LD_LIBRARY_PATH to be set)
export MCR_ROOT=/usr/local/MATLAB/MATLAB_Runtime/R2024b
export LD_LIBRARY_PATH=$MCR_ROOT/runtime/glnxa64:$MCR_ROOT/bin/glnxa64:$MCR_ROOT/sys/os/glnxa64:$LD_LIBRARY_PATH
./build/LandIce input_dir /path/to/input output_dir /path/to/output year 2024 doy 100
```

**Note**: When running the compiled executable directly (not in container), you need to specify input and output paths. The container entrypoint automatically handles this by passing `input_dir /input output_dir /output` to the application.

**Important**: 
- The executable is a binary file, NOT an installer
- It only requires MATLAB Runtime R2024b to be installed
- No MATLAB license is needed to run the compiled executable
- The runtime can be freely distributed
- MCR installation path varies by system - check your actual installation location

## Building Runtime-Only Container

### 1. Create Runtime Dockerfile

**Historical:** the current `landice/Dockerfile` already produces the runtime image as its
final stage, so this step is not needed for a normal build. Kept as a reference for
standalone runtime images. Create `Dockerfile.runtime`:
```dockerfile
FROM containers.mathworks.com/matlab-runtime:r2024b

# Copy compiled application
COPY --from=matlab-landice:r2024b /app/landice/LandIce/for_testing /opt/landice

# Set environment variables
ENV LD_LIBRARY_PATH="/opt/mcr/v913/runtime/glnxa64:/opt/mcr/v913/bin/glnxa64:/opt/mcr/v913/sys/os/glnxa64:${LD_LIBRARY_PATH}"

# Create working directory
WORKDIR /data

# Set entrypoint to the application
ENTRYPOINT ["/opt/landice/run_LandIce.sh", "/opt/mcr/v913"]
```

### 2. Build Runtime Container
```bash
docker build -f Dockerfile.runtime -t landice-runtime:latest .
```

### 3. Run the Application
```bash
docker run --rm \
  --shm-size=512M \
  -v /path/to/input:/input:ro \
  -v /path/to/output:/output \
  landice-runtime:latest \
  year 2024 \
  doy 100
```

## Environment Variables Required

The application expects these environment variables to be set:
- `OSISAF_FTP_REPROCESSED`: FTP path for reprocessed data
- `OSISAF_FTP_ARCHIVE`: FTP path for archive data  
- `OSISAF_FTP_PROD`: FTP path for production data

Set these in the Docker run command:
```bash
docker run --rm \
  --shm-size=512M \
  -e OSISAF_FTP_REPROCESSED="ftp://example.com/reprocessed" \
  -e OSISAF_FTP_ARCHIVE="ftp://example.com/archive" \
  -e OSISAF_FTP_PROD="ftp://example.com/prod" \
  -v /path/to/input:/input:ro \
  -v /path/to/output:/output \
  landice-runtime:latest \
  year 2024 \
  doy 100
```

## Troubleshooting

### License Server Connection Issues
If you get license errors, ensure:
1. The container can reach the license server
2. The license server hostname is resolvable
3. Port 7282 is accessible

### Memory Issues
If MATLAB crashes or behaves unexpectedly, increase shared memory:
```bash
docker run -it --rm --shm-size=4gb matlab-landice:r2024b
```

### Compilation Errors
If compilation fails, check:
1. All source files are present in the container
2. The project file paths are correct
3. Required toolboxes are installed

Verify toolboxes:
```bash
docker run --rm matlab-landice:r2024b matlab -batch "ver"
```