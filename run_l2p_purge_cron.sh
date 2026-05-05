#!/bin/bash
set -euo pipefail

# Daily deep-purge of the L2P download mirror.
#
# Removes any DOY directory older than SCAN_LATENCY (9) days across every
# year subdirectory under each active sensor. Trims the download area to
# just the active REA+NRT processing window so the disk doesn't grow
# unbounded as the incremental cron pulls new granules every hour.
#
# Schedule after the deep-sync (so we don't purge what we just re-pulled)
# and before MRVA (so MRVA sees only the trimmed window):
#   30 4 * * * /bin/bash ~/containerized-mur/run_l2p_purge_cron.sh

export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"

LOGDIR="${MUR_LOG_DIR:-/data1/jleach/testing/logs}"
mkdir -p "$LOGDIR"
DATE=$(date +%Y%m%d)
LOGFILE="${LOGDIR}/l2p_purge_${DATE}.log"

cd ~/containerized-mur
source .venv/bin/activate

echo "========================================" >> "$LOGFILE"
echo "L2P Deep Purge: $(date)" >> "$LOGFILE"
echo "========================================" >> "$LOGFILE"

if mur-pipeline --config config.prod.json --execute purge --deep-purge >> "$LOGFILE" 2>&1; then
    echo "SUCCESS: $(date)" >> "$LOGFILE"
else
    echo "FAILED (exit code: $?): $(date)" >> "$LOGFILE"
fi
