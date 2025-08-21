# Specify release of MATLAB
ARG MATLAB_RELEASE=R2025a

# Ubuntu-based mathworks/matlab image
FROM mathworks/matlab:$MATLAB_RELEASE AS stage0

# Copy code into container
FROM stage0 AS stage1
USER root
COPY src/ /home/matlab/Documents/MATLAB/mrva/
RUN chown -R matlab:matlab /home/matlab/Documents/MATLAB/mrva

# Compile dependencies
FROM stage1 AS stage2
RUN apt-get update && apt-get install -y make
USER matlab
WORKDIR /home/matlab/Documents/MATLAB/mrva/
RUN make install

# Set entrypoint
FROM stage2 AS stage3
ENTRYPOINT ["/usr/bin/python3", "/home/matlab/Documents/MATLAB/mrva/execute_mrva.py"]