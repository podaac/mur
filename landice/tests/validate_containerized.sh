#!/bin/bash

#Validate the containerized operation of iceland

YEAR=2025
START_DOY=187
END_DOY=187

for DOY in $(seq $START_DOY $END_DOY); do
    echo "Processing Year: $YEAR, DOY: $DOY"

    LOOP_START=$(date +%s)

    docker run --rm \
        --memory=6g \
        --memory-reservation=2g \
        --memory-swap=8g \
        --shm-size=512M \
        --cpus="2.0" \
        -e _JAVA_OPTIONS="-Xmx2048m -Xms512m -XX:+UseG1GC" \
        -e OSISAF_FTP_REPROCESSED="ftp://osisaf.met.no/reprocessed/ice/conc/v1p2" \
        -e OSISAF_FTP_ARCHIVE="https://thredds.met.no/thredds/fileServer/osisaf/met.no/ice/amsr2_conc" \
        -e OSISAF_FTP_PROD="https://thredds.met.no/thredds/fileServer/osisaf/met.no/ice/amsr2_conc" \
        -v /Users/jleach/Documents/Development/MUR/mur/landice/tests/in:/input:ro \
        -v /Users/jleach/Documents/Development/MUR/mur/landice/tests/out:/output \
        landice:latest \
        $YEAR $DOY

    if [ $? -ne 0 ]; then
        echo "Error processing Year: $YEAR, DOY: $DOY"
    fi

    LOOP_END=$(date +%s)
    DURATION=$((LOOP_END - LOOP_START))
    echo "Duration for Year: $YEAR, DOY: $DOY: ${DURATION}s"
done