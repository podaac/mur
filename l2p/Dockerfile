# Specify release of MATLAB
ARG MATLAB_RELEASE=R2025a

# Ubuntu-based mathworks/matlab image
FROM mathworks/matlab:$MATLAB_RELEASE AS stage0

# Copy code into container
FROM stage0 AS stage1
USER root
COPY src/ /home/matlab/Documents/MATLAB/l2p/
RUN chown -R matlab:matlab /home/matlab/Documents/MATLAB/l2p

# Set entrypoint
FROM stage1 AS stage2
USER matlab
WORKDIR /home/matlab/Documents/MATLAB/l2p/
ENTRYPOINT ["/usr/bin/python3", "/home/matlab/Documents/MATLAB/landice/execute_l2p.py"]