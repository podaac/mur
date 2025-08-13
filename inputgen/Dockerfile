# Create from Python3.12 image
FROM python:3.12-slim-bookworm as stage0

# Copy module
FROM stage0 as stage1
COPY ./execute_inputgen.py /app/execute_inputgen.py

# Set entrypoint
FROM stage1 AS stage2
ENTRYPOINT ["/usr/local/bin/python3", "/app/execute_inputgen.py"]