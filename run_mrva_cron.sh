#!/bin/bash
set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"

LOGDIR="${MUR_LOG_DIR:-/data1/jleach/testing/logs}"
mkdir -p "$LOGDIR"
DATE=$(date +%Y%m%d)
LOGFILE="${LOGDIR}/mrva_${DATE}.log"

cd ~/containerized-mur
source .venv/bin/activate
source ./cron_env.sh

echo "========================================" | tee -a "$LOGFILE"
echo "MUR Pipeline Run: $(date)" | tee -a "$LOGFILE"
echo "========================================" | tee -a "$LOGFILE"

# Landice sync no longer needed, can point to production via config

# Run MRVA over the full processing window (T-9 through T-1)
# Pipeline auto-detects REA (T-9..T-4) vs NRT (T-3..T-1) mode
if mur-pipeline --config "$MUR_CONFIG" --execute mrva --all-stages >> "$LOGFILE" 2>&1; then
    echo "SUCCESS: $(date)" | tee -a "$LOGFILE"
else
    echo "FAILED (exit code: $?): $(date)" | tee -a "$LOGFILE"
fi

