# Cloud-optimized browse rasters from a MUR L4 granule.
#
# Its own module, and its own container, on purpose. This work has nothing in
# common with MRVA except an input file: no MATLAB Runtime, no Fortran, no
# multi-gibibyte solve. Folding it into the mrva image would have meant
# rebuilding a MATLAB container to change a colormap, carrying GDAL through
# every mrva deployment, and coupling a cheap derived product to the slowest
# and most memory-constrained stage in the pipeline -- one that at the time of
# writing cannot finish at all on any available worker.
#
# Separate also means re-runnable. Browse rasters can be regenerated for any
# granule already in the bucket without redoing an hour of analysis, which
# matters while the render parameters are still being tuned.
FROM debian:bookworm-slim

# gdal-bin brings gdal_translate, which reads NETCDF: subdatasets and writes
# -of COG directly -- no Python, no rasterio, no build step.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gdal-bin \
    awscli \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/cache/apt/*

COPY common/bin/localize.sh /opt/cog/bin/localize.sh
COPY common/bin/maap_credentials.py /opt/cog/bin/maap_credentials.py
COPY cog/bin/entrypoint.sh /opt/cog/bin/entrypoint.sh
RUN chmod +x /opt/cog/bin/entrypoint.sh /opt/cog/bin/maap_credentials.py

ARG MUR_IMAGE_BUILD=unknown
ENV MUR_IMAGE_BUILD=${MUR_IMAGE_BUILD}

ENTRYPOINT ["/opt/cog/bin/entrypoint.sh"]
