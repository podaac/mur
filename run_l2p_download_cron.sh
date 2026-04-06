#!/bin/bash
set -euo pipefail

# Usage: run_l2p_download_cron.sh <SENSOR>
# Example cron (matching production 10-minute offsets):
#   0  * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh AMSR2R
#   10 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh AVMTBG
#   20 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh MODISA
#   30 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh MODIST

if [ $# -lt 1 ]; then
    echo "Usage: $0 <SENSOR> [SENSOR2,...]"
    echo "Example: $0 AMSR2R"
    echo "Example: $0 MODISA,MODIST"
    exit 1
fi

SENSOR="$1"

export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"

LOGDIR="/data3/jleach/testing/logs"
mkdir -p "$LOGDIR"
DATE=$(date +%Y%m%d)
LOGFILE="${LOGDIR}/l2p_download_${SENSOR}_${DATE}.log"

cd ~/containerized-mur
source .venv/bin/activate

echo "======================================== " >> "$LOGFILE"
echo "L2P Download ${SENSOR}: $(date)" >> "$LOGFILE"
echo "========================================" >> "$LOGFILE"

if mur-pipeline --config config.prod.json --execute l2p-download --sensors "$SENSOR" >> "$LOGFILE" 2>&1; then
    echo "SUCCESS: $(date)" >> "$LOGFILE"
else
    echo "FAILED (exit code: $?): $(date)" >> "$LOGFILE"
fi
