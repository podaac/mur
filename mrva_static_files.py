"""Canonical relative paths, under the static-resources root, for MRVA's
static single-file inputs (documentation/STATIC_DATA.md), mirroring
landice_static_files.py's pattern so both orchestrators resolve the same
layout one way.

Unlike landice's six fixed static files, MRVA's seasonal climatology varies
by day-of-year -- readSeasonal.m opens exactly one of the 365 mur_###.nc
files per run, never all of them (mrva/src/matlab/io/readSeasonal.m:17-20),
so it's still a single-value explicit input, just one whose relative path
depends on `doy` rather than being fixed. `seasonal_relative_path()` is kept
next to the fixed-path table for that reason.

Scope note: this only covers MRVA's static (non-per-sensor-fan-in) inputs.
It does not include the BIC/iQuam/landice per-day fan-in inputs (those need
the separate manifest mechanism -- see
docs/superpowers/specs/2026-07-27-explicit-input-contract-design.md) and it
is not yet wired into mrva4com_container.m or entrypoint.sh, since MRVA's
own explicit-args conversion (accepting named static-file flags at all)
hasn't happened yet (documentation/MAAP_EXECUTION.md section 4: MRVA is
"Not yet converted, zero path args today").
"""

MRVA_STATIC_RELATIVE_PATHS = {
    "polar_cap_edge": "landice/CylinderP01_edge.bip",
    "mur25_grid": "grids/MUR25grid.gds",
}


def seasonal_relative_path(doy: int) -> str:
    """Relative path for the single seasonal climatology file a given
    day-of-year's MRVA run needs (mrva/src/matlab/io/readSeasonal.m:17-20,
    which maps day 366 to 365)."""
    if doy == 366:
        doy = 365
    return f"seasonal/mur_{doy:03d}.nc"
