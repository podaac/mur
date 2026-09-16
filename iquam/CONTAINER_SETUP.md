# IQUAM Container Deployment Guide

## Overview

The IQUAM processing module has been containerized using a multi-stage Docker build approach. This deployment strategy compiles the MATLAB application during the build stage (requiring a valid MATLAB license) and creates a lightweight runtime container that only requires the MATLAB Runtime (MCR).

**Key Benefits:**
- **License-free runtime:** Only the build process requires a MATLAB license
- **Reproducible builds:** Consistent execution environment across systems
- **Simplified deployment:** No MATLAB installation needed on production systems
- **Automated NRT processing:** Container runs in NRT mode by default

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

The container uses a fixed directory structure optimized for volume mounting:

```
/data/                          # Container working directory
├── output/iquam/              # Output .bii files (REQUIRED mount)
│   └── YYYY/
│       └── Global_IQUAM0_YYYY_DDD.bii
├── cache/iquam/               # Monthly NetCDF cache (REQUIRED mount)
│   └── iquam.YYYY.MM.mat
├── logs/                      # Processing logs (REQUIRED mount)
│   └── buoy.log
└── /tmp/makebic/              # Temporary workspace (ephemeral)
```

## Volume Mounts

### Required Mounts

These directories must be mounted from the host system for the container to function correctly:

| Container Path | Purpose | Access | Typical Host Path | Notes |
|----------------|---------|--------|-------------------|-------|
| `/data/output/iquam` | Daily .bii output files | Read/Write | `/data/iquam/output` | Organized by year subdirectories |
| `/data/cache/iquam` | Monthly NetCDF cache | Read/Write | `/data/iquam/cache` | Avoids re-downloading data |
| `/data/logs` | Processing logs | Read/Write | `/data/iquam/logs` | Contains buoy.log |

### Volume Persistence

**Important:** The cache directory (`/data/cache/iquam`) should be a persistent volume to avoid re-downloading large NetCDF files (~500MB per month) on each container run.

**Storage Requirements:**
- **Output:** ~5 MB per day, ~1.8 GB per year
- **Cache:** ~100 MB per month processed, ~1.2 GB per year
- **Logs:** Grows indefinitely (rotate externally)
- **Temporary:** ~500 MB peak (ephemeral, can use tmpfs)

## Building the Container

### Prerequisites

- Docker or compatible container runtime
- Network access to JPL MATLAB license servers during build
- Valid MATLAB and MATLAB Compiler licenses
- ~10 GB disk space for build process

### Build Command

**IMPORTANT:** The Dockerfile references shared utilities from the `../common` folder, so the build context must include the parent `mur` directory. Build from within the iquam directory and set the context to the parent (`..`).

```bash
# Navigate to the iquam directory
cd mur/iquam

# Build for AMD64 (most common Linux servers)
docker build --platform linux/amd64 -f Dockerfile -t iquam:latest ..

# Or using Apple's container tools on macOS
container build --arch amd64 -f Dockerfile -t iquam:latest ..
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
3. Increase timeout in Dockerfile line 72: `timeout 600s` → `timeout 1200s`

## Running the Container

### Basic Usage

The container runs in **NRT mode by default** and processes the most recent available data:

```bash
docker run --rm \
  --shm-size=512M \
  -v /local/path/output:/data/output/iquam \
  -v /local/path/cache:/data/cache/iquam \
  -v /local/path/logs:/data/logs \
  iquam:latest
```

### NRT Mode Operation

When the container runs, it automatically:
1. Calculates the current date and determines the processing window (last 9 days)
2. Downloads monthly IQUAM NetCDF files from NOAA STAR (if not cached)
3. Extracts and processes daily observations
4. Filters observations by quality level (≥5)
5. Writes binary .bii files to `/data/output/iquam/YYYY/`
6. Logs all operations to `/data/logs/buoy.log`

**Processing Window Details:**
- **NRT Latency:** 1 day behind current date
- **Scan Window:** 9 days backward
- **Stability Window:** 2 days (files older than 2 days are not reprocessed)
- **Temporal Range:** ±3 days for each analysis day

### Scheduled Execution

For operational NRT processing, run the container on a daily schedule:

**Using cron:**
```bash
# Add to crontab (runs daily at 12:00 UTC)
0 12 * * * /usr/bin/docker run --rm \
  --shm-size=512M \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest >> /var/log/iquam_cron.log 2>&1
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
ExecStart=/usr/bin/docker run --rm \
  --shm-size=512M \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest

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
  iquam:latest
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
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest
```

**Resource Guidelines:**
- **Minimum RAM:** 2 GB
- **Recommended RAM:** 4 GB
- **CPUs:** 1-2 (processing is I/O bound, not CPU intensive)
- **Disk I/O:** Fast storage for cache directory improves performance

### MCR Cache Optimization

Optimize MATLAB Runtime caching:

```bash
docker run --rm \
  --shm-size=512M \
  -e MCR_CACHE_ROOT=/tmp/mcr_cache \
  -e MCR_CACHE_SIZE=1024M \
  -e MCR_CACHE_VERBOSE=true \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest
```

### Network Optimization

The container downloads data from NOAA STAR servers. If multiple containers run concurrently or network bandwidth is limited:

1. **Use a shared cache volume** across multiple container instances
2. **Pre-download NetCDF files** to the cache directory
3. **Set download timeouts** if using unreliable networks (requires modifying makedailyiquam.m)

## Data Management

### Cache Management

The cache directory stores monthly MATLAB `.mat` files derived from IQUAM NetCDF downloads. These files are regenerated if:
- The source NetCDF is newer than the cached .mat file
- The cached file is corrupted or missing
- The `rewrite` flag is set

**Cache Cleanup Strategy:**

```bash
# Remove cache files older than 1 year (optional)
find /data/iquam/cache -name "iquam.*.mat" -mtime +365 -delete

# Remove specific month cache to force re-download
rm /data/iquam/cache/iquam.2024.10.mat
```

**Note:** Deleting cache files forces re-download (~500MB per month) on next run.

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
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest

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
            image: iquam:latest
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
            - name: cache
              mountPath: /data/cache/iquam
            - name: logs
              mountPath: /data/logs
            - name: shm
              mountPath: /dev/shm
          volumes:
          - name: output
            persistentVolumeClaim:
              claimName: iquam-output-pvc
          - name: cache
            persistentVolumeClaim:
              claimName: iquam-cache-pvc
          - name: logs
            persistentVolumeClaim:
              claimName: iquam-logs-pvc
          - name: shm
            emptyDir:
              medium: Memory
              sizeLimit: 512Mi
```

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
  name: iquam-cache-pvc
  namespace: mur-sst
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
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
    image: iquam:latest
    shm_size: 512m
    mem_limit: 4g
    mem_reservation: 2g
    cpus: 2.0
    volumes:
      - iquam-output:/data/output/iquam
      - iquam-cache:/data/cache/iquam
      - iquam-logs:/data/logs
    environment:
      - MCR_CACHE_ROOT=/tmp/mcr_cache
      - MCR_CACHE_SIZE=1024M
    restart: "no"  # Run once, don't restart automatically

volumes:
  iquam-output:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /data/iquam/output
  iquam-cache:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /data/iquam/cache
  iquam-logs:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /data/iquam/logs
```

Run manually:
```bash
docker-compose up
```

Or schedule with cron:
```bash
# Run via cron
0 12 * * * cd /path/to/docker-compose && /usr/local/bin/docker-compose up >> /var/log/iquam.log 2>&1
```

## Security Considerations

### Running as Non-Root

To improve security, run the container as a non-root user:

```bash
docker run --rm \
  --shm-size=512M \
  --user $(id -u):$(id -g) \
  -v /data/iquam/output:/data/output/iquam \
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest
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
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest
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
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest
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
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest \
  /bin/bash

# Manually run entrypoint to see errors
/opt/iquam/bin/entrypoint.sh
```

**Common causes:**
- Missing or inaccessible volume mounts
- Insufficient permissions on mounted directories
- MCR initialization failure (check shm-size)

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
  iquam:latest \
  touch /data/output/iquam/test.txt
```

**Common causes:**
- Output directory not writable
- Data download failures (check network/firewall)
- NOAA server unavailable
- Incorrect date calculation (future dates skipped)

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
  -v /data/iquam/cache:/data/cache/iquam \
  -v /data/iquam/logs:/data/logs \
  iquam:latest
```

### Network Download Failures

**Symptoms:** wget errors in logs, missing cache files

**Check:**
```bash
# Test connectivity to NOAA STAR
curl -I https://www.star.nesdis.noaa.gov/pub/socd/sst/iquam/v2.10/

# Check if firewall/proxy is blocking
docker run --rm iquam:latest \
  wget --spider https://www.star.nesdis.noaa.gov/pub/socd/sst/iquam/v2.10/
```

**Solutions:**
- Configure proxy settings if behind corporate firewall
- Add retry logic for transient failures
- Use alternative download method (ftp vs https)

## Future Enhancements

### REA Mode Support

Currently, the container operates in **NRT mode only**. Future enhancements will add REA mode with:
- Temporal aggregation (±3 day windows)
- Platform-specific error weighting
- Output of `.biq` files for analysis

To enable REA mode (when implemented), modify the entrypoint to set `config.enableREA = true`.

### Multi-Architecture Builds

Current build targets `linux/amd64`. To support ARM64 (AWS Graviton, Apple Silicon):

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile \
  -t iquam:latest \
  --push \
  .
```

### Configuration Flexibility

Future versions may expose additional configuration options via environment variables:
- `IQUAM_NRT_LATENCY` - Override NRT latency
- `IQUAM_SCAN_WINDOW` - Override scan window
- `IQUAM_QUALITY_THRESHOLD` - Override quality filtering
- `IQUAM_SOURCE_URL` - Override NOAA data source

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
