#!/bin/bash
set -euo pipefail

# Daily deep-sync of the L2P download mirror.
#
# Re-queries CMR for the trailing 9 days using -sd/-ed (bypassing each
# collection's .update watermark) and downloads any granule that's missing on
# disk. The .update watermark is saved before and restored after, so the
# normal hourly incremental cron is unaffected.
#
# Why: podaac-data-subscriber's incremental mode advances .update past granule
# revision-dates that were never actually persisted to disk (download miss,
# CMR pagination quirk, or NRT publication race). Once .update is past a
# granule's revision-date, no future incremental tick will fetch it. A daily
# windowed re-query closes that gap before MRVA runs.
#
# Run before MRVA. If MRVA is at 07:05 UTC, schedule this at e.g. 04:00 UTC
# to give the deep-sync time to finish:
#   0 4 * * * /bin/bash ~/containerized-mur/run_l2p_deepsync_cron.sh
#
# Usage: run_l2p_deepsync_cron.sh [DAYS]
#   DAYS defaults to 9 (matches the MRVA REA+NRT processing window).

DAYS="${1:-9}"

export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"

LOGDIR="${MUR_LOG_DIR:-/data1/jleach/testing/logs}"
mkdir -p "$LOGDIR"
DATE=$(date +%Y%m%d)
LOGFILE="${LOGDIR}/l2p_deepsync_${DATE}.log"

cd ~/containerized-mur
source .venv/bin/activate

echo "========================================" >> "$LOGFILE"
echo "L2P Deep Sync (last ${DAYS} days): $(date)" >> "$LOGFILE"
echo "========================================" >> "$LOGFILE"

if mur-pipeline --config config.prod.json --execute l2p-download --deep-sync-days "$DAYS" >> "$LOGFILE" 2>&1; then
    echo "SUCCESS: $(date)" >> "$LOGFILE"
else
    echo "FAILED (exit code: $?): $(date)" >> "$LOGFILE"
fi
