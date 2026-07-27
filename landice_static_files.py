"""Canonical relative paths, under the static-resources root, for landice's
six explicit static inputs (documentation/STATIC_DATA.md).

Shared by run_mur_pipeline.py (joins against a local directory) and
run_mur_maap.py (joins against an S3 prefix) so the mapping is defined once.
"""

LANDICE_STATIC_RELATIVE_PATHS = {
    "landmask_p011": "grids/maskGlob1km.gds",
    "gridindex_north_p011": "mat/p011/saf2north.mat",
    "gridindex_south_p011": "mat/p011/saf2south.mat",
    "landmask_p01": "grids/maskGLOBp01deg.gds",
    "gridindex_north_p01": "mat/p01/saf2north.mat",
    "gridindex_south_p01": "mat/p01/saf2south.mat",
}
