#!/bin/bash
set -euo pipefail

# Usage: run_l2p_download_cron.sh <SENSOR>
#
# Production-aligned cron schedule (mirrors mur_cron/README.md exactly):
#   0  * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh AMSR2R_FINAL
#   10 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh AMSR2R_RT
#   20 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh AVMTBG
#   30 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh MODISA
#   40 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh MODIST
#
# AMSR2R_FINAL and AMSR2R_RT are aliases that download a single AMSR2R
# collection at a time (matching prod's separate amsr2r.sh and amsr2r_rt.sh
# scripts). The bare "AMSR2R" alias still works and downloads both back-to-back.

if [ $# -lt 1 ]; then
    echo "Usage: $0 <SENSOR>"
    echo "Sensors: AMSR2R, AMSR2R_FINAL, AMSR2R_RT, AVMTBG, MODISA, MODIST"
    exit 1
fi

SENSOR_ARG="$1"

# Translate AMSR2R_FINAL / AMSR2R_RT aliases into a (--sensors, --collection) pair.
case "$SENSOR_ARG" in
    AMSR2R_FINAL)
        SENSOR="AMSR2R"
        COLLECTION="AMSR2-REMSS-L2P-v8.2"
        ;;
    AMSR2R_RT)
        SENSOR="AMSR2R"
        COLLECTION="AMSR2-REMSS-L2P_RT-v8.2"
        ;;
    *)
        SENSOR="$SENSOR_ARG"
        COLLECTION=""
        ;;
esac

export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"

LOGDIR="${MUR_LOG_DIR:-/data1/jleach/testing/logs}"
mkdir -p "$LOGDIR"
DATE=$(date +%Y%m%d)
# Use the original arg for the log filename so AMSR2R_FINAL and AMSR2R_RT log
# to separate files, matching prod's per-script log layout.
LOGFILE="${LOGDIR}/l2p_download_${SENSOR_ARG}_${DATE}.log"

cd ~/containerized-mur
source .venv/bin/activate
source ./cron_env.sh

echo "======================================== " >> "$LOGFILE"
echo "L2P Download ${SENSOR_ARG}: $(date)" >> "$LOGFILE"
echo "========================================" >> "$LOGFILE"

CMD=(mur-pipeline --config "$MUR_CONFIG" --execute l2p-download --sensors "$SENSOR")
if [ -n "$COLLECTION" ]; then
    CMD+=(--collection "$COLLECTION")
fi

if "${CMD[@]}" >> "$LOGFILE" 2>&1; then
    echo "SUCCESS: $(date)" >> "$LOGFILE"
else
    echo "FAILED (exit code: $?): $(date)" >> "$LOGFILE"
fi
