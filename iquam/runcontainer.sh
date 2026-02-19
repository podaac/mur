docker run --rm \
  --memory=8g \
  --memory-swap=8g \
  --shm-size=2g \
  -v /Users/jleach/Documents/Development/MUR/mur/iquam/testing/output:/data/output/iquam \
  -v /Users/jleach/Documents/Development/MUR/mur/iquam/testing/cache:/data/cache/iquam \
  -v /Users/jleach/Documents/Development/MUR/mur/iquam/testing/logs:/data/logs \
  iquam:latest \
  /tmp/makebic \
  /data/logs \
  /data/output/iquam \
  /data/cache/iquam