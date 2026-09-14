# IQUAM Container Deployment Guide

## Overview

The IQUAM processing module has been containerized using a multi-stage Docker build approach. This deployment strategy compiles the MATLAB application during the build stage (requiring a valid MATLAB license) and creates a lightweight runtime container that only requires the MATLAB Runtime (MCR).

**Key Benefits:**
- **License-free runtime:** Only the build process requires a MATLAB license
- **Reproducible builds:** Consistent execution environment across systems
- **Simplified deployment:** No MATLAB installation needed on production systems
- **Explicit inputs:** Every invocation is told exactly which day, mode, and reference date to process — the container never infers "today" or a processing window itself

## Architecture

### Multi-Stage Build Process

The container build uses two stages:

**Stage 1: Builder (requires MATLAB license)**
- Base image: `mathworks/matlab:r2024b`
- Compiles MATLAB code using MATLAB Compiler (mcc)
- Requires network access to JPL license servers
- Produces standalone executable (`IquamProcessor`)

**Stage 2: Runtime (no license required)**
- Base image: `containers.mathworks.com/matlab-runtime:r2024b`
- Contains only the compiled application and MATLAB Runtime
- Significantly smaller than full MATLAB installation
- Can run anywhere without license dependencies

### Directory Structure

The container uses a fixed directory structure optimized for volume mounting. There is no cache directory — the module has never persisted downloaded NetCDF data between runs (see `makedailyiquam.m`'s own comment: "no persistent cache needed... matches production behavior and avoids cache staleness issues").

```
/data/                          # Container working directory
├── output/iquam/              # Output .bii files (REQUIRED mount)
│   └── YYYY/
│       └── Global_IQUAM0_YYYY_DDD.bii
├── logs/                      # Processing logs (REQUIRED mount)
│   └── buoy.log
└── /tmp/makebic/              # Temporary workspace (ephemeral, not mounted)
```

## Volume Mounts

### Required Mounts

These directories must be mounted from the host system for the container to function correctly:

| Container Path | Purpose | Access | Typical Host Path | Notes |
|----------------|---------|--------|-------------------|-------|
| `/data/output/iquam` | Daily .bii output files | Read/Write | `/data/iquam/output` | Organized by year subdirectories |
| `/data/logs` | Processing logs | Read/Write | `/data/iquam/logs` | Contains buoy.log |

`/tmp/makebic` (the working directory) does not need a host mount — it's ephemeral scratch space inside the container, cleaned at the start of each run.

### Volume Persistence

**Storage Requirements:**
- **Output:** ~5 MB per day, ~1.8 GB per year
- **Logs:** Grows indefinitely (rotate externally)
- **Temporary:** ~500 MB peak (ephemeral, can use tmpfs)

## Building the Container

### Prerequisites

- Docker or compatible container runtime
- Network access to JPL MATLAB license servers during build
- Valid MATLAB and MATLAB Compiler licenses
- `network.lic` in the `mur/` directory (`cp network.lic.example network.lic`, then edit)
- ~10 GB disk space for build process

### Build Command

Use `build_module.sh` from the `mur/` directory:

```bash
cd mur
./build_module.sh iquam
```

That builds the `mur-matlab-base:r2024b` image first if it's missing, verifies
`network.lic`, builds `--platform linux/amd64` with the parent `mur/` directory as
context, and tags the image `mur-iquam:latest` — the name the pipeline config expects.

### Manual Build (Advanced)

Only needed when `build_module.sh` doesn't fit: a custom tag, an external CI system, or
debugging the Dockerfile itself.

**IMPORTANT:** The Dockerfile references shared utilities from the `../common` folder, so
the build context must include the parent `mur` directory. Build from within the iquam
directory and set the context to the parent (`..`). The base image must already exist —
build it with `./build_matlab_base.sh` first.

```bash
# Navigate to the iquam directory
cd mur/iquam

# Build for AMD64 (most common Linux servers)
docker build --platform linux/amd64 -f Dockerfile -t mur-iquam:latest ..

# Or using Apple's container tools on macOS
container build --arch amd64 -f Dockerfile -t mur-iquam:latest ..
```

**Note:** The `..` at the end sets the build context to the parent `mur` directory, which allows the Dockerfile to access both `iquam/` and `common/` folders.

### Build Process Timeline

- **Downloading base images:** 2-5 minutes
- **Installing dependencies:** 1-2 minutes
- **MATLAB compilation:** 3-8 minutes
- **Creating runtime image:** 1-2 minutes
- **Total:** 7-17 minutes (varies by network speed and system)

### Build Troubleshooting

**Build hangs at compilation step:**

Common causes:
- License servers unreachable (firewall/network issues)
- No available licenses (all seats in use)
- VPN required for license access
- Incorrect license server configuration

**Compilation timeout (>10 minutes):**

The Dockerfile includes a 10-minute timeout for the mcc compilation. If your build consistently times out:
1. Verify license server is responding
2. Check that MATLAB Compiler license is available (not just base MATLAB)
3. Increase timeout in Dockerfile: `timeout 600s` → `timeout 1200s`

## Running the Container

### Basic Usage

The container is **named-args-only** — it does not infer the date, mode, or window itself. All nine flags below are required; there is no "run with defaults" invocation:

```bash
docker run --rm \
  --shm-size=512M \
  -v /local/path/output:/data/output/iquam \
  -v /local/path/logs:/data/logs \
  mur-iquam:latest \
  --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

### What One Invocation Does

Given the flags above, the container:
1. Downloads monthly IQUAM NetCDF files from NOAA STAR for the `±buoy-day-range` window around the target day (no cache — always freshly downloaded)
2. Extracts and processes daily observations for each offset day in that window
3. Filters observations by quality level (≥5)
4. Writes binary .bii files to `/data/output/iquam/YYYY/` for each offset day that needs (re)processing
5. Logs all operations to `/data/logs/buoy.log`

**Who decides what to process:** the calling orchestrator (`run_mur_pipeline.py`/`run_mur_maap.py`) decides the target day, the NRT/REA mode, and the reference date — normally by iterating a 9-day scan window (1-day NRT latency, 4-day REA latency) and invoking this container once per day in that window. The container itself only ever processes the one day (plus its own `±buoy-day-range` sub-window) it's explicitly told about via flags:

- **`--buoy-day-range`:** temporal window processed per invocation (±days around the target day)
- **`--stability-latency`:** files older than this many days (relative to `--reference-date`) are not reprocessed unless missing

### Scheduled Execution

For operational NRT processing, run the container on a daily schedule. The example below uses `date` to compute the flag values for "today" — in practice, prefer driving this from `run_mur_pipeline.py` (which already computes the NRT/REA window and mode) rather than reimplementing that logic in a shell script.

**Using cron:**
```bash
# Add to crontab (runs daily at 12:00 UTC)
0 12 * * * YEAR=$(date -u -d yesterday +\%Y) DOY=$(date -u -d yesterday +\%j) REF=$(date -u +\%Y-\%m-\%d) && \
  /usr/bin/docker run --rm \
  --shm-size=512M \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  mur-iquam:latest \
  --year "$YEAR" --doy "$DOY" --mode nrt --reference-date "$REF" \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2 >> /var/log/iquam_cron.log 2>&1
```

**Using systemd timer:**
```ini
# /etc/systemd/system/iquam-processor.service
[Unit]
Description=IQUAM SST Processing
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
Environment=YEAR=%Y DOY=%j
ExecStart=/bin/sh -c '/usr/bin/docker run --rm \
  --shm-size=512M \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  mur-iquam:latest \
  --year $(date -u +%%Y) --doy $(date -u +%%j) --mode nrt --reference-date $(date -u +%%Y-%%m-%%d) \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2'

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/iquam-processor.timer
[Unit]
Description=Run IQUAM Processing Daily
Requires=iquam-processor.service

[Timer]
OnCalendar=daily
Persistent=true
Unit=iquam-processor.service

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
systemctl enable iquam-processor.timer
systemctl start iquam-processor.timer
```

## Performance Optimization

### Required: Shared Memory

MATLAB Runtime requires adequate shared memory. **Always** include `--shm-size=512M`:

```bash
docker run --rm \
  --shm-size=512M \
  [other options] \
  mur-iquam:latest \
  --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

**Without this flag, the container may:**
- Fail with cryptic MCR errors
- Hang indefinitely
- Crash with segmentation faults

### Memory Allocation

For processing large monthly files:

```bash
docker run --rm \
  --shm-size=512M \
  --memory="4g" \
  --memory-reservation="2g" \
  --memory-swap="6g" \
  --cpus="2.0" \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  mur-iquam:latest \
  --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

**Resource Guidelines:**
- **Minimum RAM:** 2 GB
- **Recommended RAM:** 4 GB
- **CPUs:** 1-2 (processing is I/O bound, not CPU intensive)

### MCR Cache Optimization

This is the **MATLAB Runtime's own** startup cache (unrelated to IQUAM data — there is no IQUAM data cache). Optimize it the same way as the other containers in this pipeline:

```bash
docker run --rm \
  --shm-size=512M \
  -e MCR_CACHE_ROOT=/tmp/mcr_cache \
  -e MCR_CACHE_SIZE=1024M \
  -e MCR_CACHE_VERBOSE=true \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  mur-iquam:latest \
  --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

### Network Optimization

The container downloads data from NOAA STAR servers on every run (there is no cache to avoid re-downloading). If multiple containers run concurrently or network bandwidth is limited:

1. **Stagger scheduled runs** rather than launching many containers at once
2. **Set download timeouts** if using unreliable networks (requires modifying `makedailyiquam.m`)

## Data Management

### Log Management

The `buoy.log` file grows indefinitely. Implement log rotation:

**Using logrotate:**
```
# /etc/logrotate.d/iquam
/data/iquam/logs/buoy.log {
    daily
    rotate 30
    compress
    missingok
    notifempty
    create 0644 root root
}
```

### Output File Retention

Output `.bii` files are organized by year:
```
/data/output/iquam/
├── 2023/
│   ├── Global_IQUAM0_2023_001.bii
│   ├── Global_IQUAM0_2023_002.bii
│   └── ...
├── 2024/
│   ├── Global_IQUAM0_2024_001.bii
│   └── ...
```

**Retention recommendations:**
- **NRT processing:** Keep current year + 1 previous year
- **Reanalysis:** Archive all years (required for consistency)
- **Backup:** Consider backing up to object storage (S3, etc.)

## Monitoring and Health Checks

### Container Health Check

Add a health check to ensure the container completed successfully:

```bash
# Check exit code of last run
docker run --rm \
  --shm-size=512M \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  mur-iquam:latest \
  --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "IQUAM processing failed with exit code $EXIT_CODE"
    # Send alert (email, Slack, PagerDuty, etc.)
fi
```

### Log Monitoring

Monitor the log file for errors or unexpected patterns:

```bash
# Check for common error patterns
grep -i "error\|failed\|cannot" /data/iquam/logs/buoy.log | tail -20

# Check today's processing
TODAY=$(date +"%Y-%m-%d")
grep "$TODAY" /data/iquam/logs/buoy.log

# Check observation counts (should be 400k-800k daily)
grep "observations" /data/iquam/logs/buoy.log | tail -10
```

### Output Validation

Verify output files were created:

```bash
# Check if today's file exists
YEAR=$(date +"%Y")
DOY=$(date +"%j")
OUTPUT_FILE="/data/iquam/output/${YEAR}/Global_IQUAM0_${YEAR}_${DOY}.bii"

if [ -f "$OUTPUT_FILE" ]; then
    FILE_SIZE=$(stat -f%z "$OUTPUT_FILE" 2>/dev/null || stat -c%s "$OUTPUT_FILE")
    if [ $FILE_SIZE -lt 100000 ]; then
        echo "WARNING: Output file suspiciously small ($FILE_SIZE bytes)"
    else
        echo "Output file created successfully ($FILE_SIZE bytes)"
    fi
else
    echo "ERROR: Expected output file not found: $OUTPUT_FILE"
fi
```

## Kubernetes Deployment

### CronJob Example

For Kubernetes environments, deploy as a CronJob:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: iquam-processor
  namespace: mur-sst
spec:
  schedule: "0 12 * * *"  # Daily at 12:00 UTC
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  concurrencyPolicy: Forbid  # Don't run concurrent jobs
  jobTemplate:
    spec:
      template:
        metadata:
          labels:
            app: iquam-processor
        spec:
          restartPolicy: OnFailure
          containers:
          - name: iquam
            image: mur-iquam:latest
            args:
              - "--year"
              - "2026"
              - "--doy"
              - "220"
              - "--mode"
              - "nrt"
              - "--reference-date"
              - "2026-08-09"
              - "--work-dir"
              - "/tmp/makebic"
              - "--log-dir"
              - "/data/logs"
              - "--output-dir"
              - "/data/output/iquam"
              - "--buoy-day-range"
              - "3"
              - "--stability-latency"
              - "2"
            resources:
              requests:
                memory: "2Gi"
                cpu: "1"
              limits:
                memory: "4Gi"
                cpu: "2"
            volumeMounts:
            - name: output
              mountPath: /data/output/iquam
            - name: logs
              mountPath: /data/logs
            - name: shm
              mountPath: /dev/shm
          volumes:
          - name: output
            persistentVolumeClaim:
              claimName: iquam-output-pvc
          - name: logs
            persistentVolumeClaim:
              claimName: iquam-logs-pvc
          - name: shm
            emptyDir:
              medium: Memory
              sizeLimit: 512Mi
```

(In practice, the `--year`/`--doy`/`--mode`/`--reference-date` values need to be computed fresh per run rather than hardcoded as shown here — e.g. by templating this manifest from `run_mur_pipeline.py`'s own window/mode calculation, or by wrapping the CronJob's command in a small script that computes them at container start.)

### Persistent Volume Claims

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: iquam-output-pvc
  namespace: mur-sst
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: iquam-logs-pvc
  namespace: mur-sst
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

## Docker Compose Deployment

For single-server deployments, use Docker Compose:

```yaml
# docker-compose.yml
version: '3.8'

services:
  iquam-processor:
    image: mur-iquam:latest
    shm_size: 512m
    mem_limit: 4g
    mem_reservation: 2g
    cpus: 2.0
    volumes:
      - iquam-output:/data/output/iquam
      - iquam-logs:/data/logs
    environment:
      - MCR_CACHE_ROOT=/tmp/mcr_cache
      - MCR_CACHE_SIZE=1024M
    command:
      - "--year"
      - "${YEAR}"
      - "--doy"
      - "${DOY}"
      - "--mode"
      - "${MODE}"
      - "--reference-date"
      - "${REFERENCE_DATE}"
      - "--work-dir"
      - "/tmp/makebic"
      - "--log-dir"
      - "/data/logs"
      - "--output-dir"
      - "/data/output/iquam"
      - "--buoy-day-range"
      - "3"
      - "--stability-latency"
      - "2"
    restart: "no"  # Run once, don't restart automatically

volumes:
  iquam-output:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /data/iquam/output
  iquam-logs:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /data/iquam/logs
```

Run manually (with `YEAR`/`DOY`/`MODE`/`REFERENCE_DATE` set in the environment or a `.env` file):
```bash
YEAR=2026 DOY=220 MODE=nrt REFERENCE_DATE=2026-08-09 docker-compose up
```

## Security Considerations

### Running as Non-Root

To improve security, run the container as a non-root user:

```bash
docker run --rm \
  --shm-size=512M \
  --user $(id -u):$(id -g) \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  mur-iquam:latest \
  --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

**Important:** Ensure mounted directories have appropriate permissions for the specified UID/GID.

### Read-Only Root Filesystem

For additional security, run with a read-only root filesystem:

```bash
docker run --rm \
  --shm-size=512M \
  --read-only \
  --tmpfs /tmp:size=2g \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  mur-iquam:latest \
  --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

### Network Isolation

If running in a restricted environment, allow outbound connections only to NOAA STAR:

```bash
# Using Docker network with egress filtering
docker network create --driver bridge iquam-net
docker run --rm \
  --network iquam-net \
  --shm-size=512M \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  mur-iquam:latest \
  --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

## Troubleshooting

### Container Exits Immediately

**Symptoms:** Container starts and exits with code 0 or 1

**Check:**
```bash
# Run with interactive terminal to see errors
docker run -it --rm \
  --shm-size=512M \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  --entrypoint /bin/bash \
  mur-iquam:latest

# Manually run entrypoint to see errors (all 9 flags required)
/opt/iquam/bin/entrypoint.sh --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

**Common causes:**
- Missing or inaccessible volume mounts
- Insufficient permissions on mounted directories
- MCR initialization failure (check shm-size)
- A required flag omitted, or an unrecognized flag passed — the entrypoint prints a usage message and exits non-zero (positional arguments are not accepted at all)

### No Output Files Created

**Symptoms:** Container completes but no .bii files appear

**Check:**
```bash
# Examine logs
tail -100 /data/iquam/logs/buoy.log

# Look for specific error patterns
grep -i "error\|cannot\|failed" /data/iquam/logs/buoy.log

# Verify output directory is writable
docker run --rm \
  -v /data/iquam/output:/data/output/iquam \
  --entrypoint /bin/sh \
  mur-iquam:latest \
  -c "touch /data/output/iquam/test.txt"
```

**Common causes:**
- Output directory not writable
- Data download failures (check network/firewall)
- NOAA server unavailable
- `--reference-date` is in the past relative to the day being processed, so every offset day in the `±buoy-day-range` window was skipped as a future date

### Memory Errors

**Symptoms:** Container killed by OOM killer or crashes with memory errors

**Solution:**
```bash
# Increase memory limits
docker run --rm \
  --shm-size=512M \
  --memory="8g" \
  --memory-swap="16g" \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/logs:/data/logs \
  mur-iquam:latest \
  --year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
  --work-dir /tmp/makebic --log-dir /data/logs --output-dir /data/output/iquam \
  --buoy-day-range 3 --stability-latency 2
```

### Network Download Failures

**Symptoms:** wget errors in logs

**Check:**
```bash
# Test connectivity to NOAA STAR
curl -I https://www.star.nesdis.noaa.gov/pub/socd/sst/iquam/v2.10/

# Check if firewall/proxy is blocking
docker run --rm --entrypoint wget mur-iquam:latest \
  --spider https://www.star.nesdis.noaa.gov/pub/socd/sst/iquam/v2.10/
```

**Solutions:**
- Configure proxy settings if behind corporate firewall
- Add retry logic for transient failures
- Use alternative download method (ftp vs https)

## Future Enhancements

### REA Mode Support

Currently, REA aggregation (`refbii2biq.m`) is stubbed, not implemented — passing `--mode rea` runs the container in REA *latency* mode (the stability-window/rewrite behavior changes) but does not produce aggregated `.biq` output yet. Future enhancements will add:
- Temporal aggregation (±3 day windows)
- Platform-specific error weighting
- Output of `.biq` files for analysis

Enabling REA aggregation (when implemented) will be via `buoyDataProcessing.m`'s `enableREA` parameter, which is not exposed as a container flag today.

### Multi-Architecture Builds

Current build targets `linux/amd64` (`build_module.sh` hard-codes it). Multi-arch support
for ARM64 (AWS Graviton, Apple Silicon) would need a manual `buildx` invocation — note the
parent build context, same as every other manual build:

```bash
cd mur/iquam
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile \
  -t mur-iquam:latest \
  --push \
  ..
```

This also requires an ARM64 `mur-matlab-base` image, which MathWorks does not currently publish.

### Configuration Flexibility

Every input this container needs is already an explicit named flag (`--year`, `--doy`, `--mode`, `--reference-date`, `--work-dir`, `--log-dir`, `--output-dir`, `--buoy-day-range`, `--stability-latency`) — there's no remaining case for environment-variable overrides of these values. `--source-url` remains a MATLAB-side default (`buoyDataProcessing.m`), not exposed as a flag; that would be a natural next addition if a use case for overriding it arises.

## Additional Resources

- [IQUAM README](README.md) - Detailed information about data flow and processing
- [NOAA IQUAM Documentation](https://www.star.nesdis.noaa.gov/sod/sst/iquam/) - Upstream data source
- [MATLAB Runtime Documentation](https://www.mathworks.com/help/compiler/matlab-runtime.html) - MCR details
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/) - Container optimization

## Support

For issues related to:
- **Container build/deployment:** Contact MUR development team
- **MATLAB licensing:** Contact JPL CAE license administrators
- **IQUAM data availability:** Check NOAA STAR service status
- **MUR SST processing:** See main MUR documentation
