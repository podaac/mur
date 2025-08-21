# Specify release of MATLAB
ARG MATLAB_RELEASE=R2025a

# Ubuntu-based mathworks/matlab image
FROM mathworks/matlab:$MATLAB_RELEASE AS stage0

# Create a Python virtual environment and install requirements
FROM stage0 AS stage1
USER root
COPY requirements.txt /app/requirements.txt
RUN /usr/bin/python3 -m venv /app/env \
    && /app/env/bin/pip install -r /app/requirements.txt

# Copy code into container
FROM stage1 AS stage2
COPY src/ /home/matlab/Documents/MATLAB/l2p/
RUN chown -R matlab:matlab /home/matlab/Documents/MATLAB/l2p

# Copy .netrc file
FROM stage2 AS stage3
COPY .netrc /home/matlab/.netrc
RUN chmod 600 /home/matlab/.netrc && chown matlab:matlab /home/matlab/.netrc

# Set entrypoint
FROM stage3 AS stage4
USER matlab
WORKDIR /home/matlab/Documents/MATLAB/l2p/
ENTRYPOINT ["/app/env/bin/python3", "/home/matlab/Documents/MATLAB/l2p/execute_l2p.py"]