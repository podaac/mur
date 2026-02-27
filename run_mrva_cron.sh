#!/bin/bash
set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"

LOGDIR="/data3/jleach/testing/logs"
mkdir -p "$LOGDIR"
DATE=$(date +%Y%m%d)
LOGFILE="${LOGDIR}/mrva_${DATE}.log"

cd ~/containerized-mur
source .venv/bin/activate

echo "========================================" | tee -a "$LOGFILE"
echo "MUR Pipeline Run: $(date)" | tee -a "$LOGFILE"
echo "========================================" | tee -a "$LOGFILE"

# Sync landice
YEAR=$(date +%Y)
rsync -av "/nas2/landice/${YEAR}/" "/data3/jleach/testing/ops-landice/land/p01/${YEAR}/" >> "$LOGFILE" 2>&1

# Run MRVA over the full processing window (T-9 through T-1)
# Pipeline auto-detects REA (T-9..T-4) vs NRT (T-3..T-1) mode
if mur-pipeline --config config.prod.json --execute mrva --all-stages >> "$LOGFILE" 2>&1; then
    echo "SUCCESS: $(date)" | tee -a "$LOGFILE"
else
    echo "FAILED (exit code: $?): $(date)" | tee -a "$LOGFILE"
fi

