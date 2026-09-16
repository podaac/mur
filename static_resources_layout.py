"""The static-resources layout, in one place.

Which files live where under the static-resources root was previously spelled
out four times -- landice_static_files.py, mrva_static_files.py,
utils/bundle_prod_static.sh, and utils/measure_static_sizes.py. Adding a fifth
copy inside the S3 uploader is how such tables drift, so the uploader and its
verifier import this module, which in turn imports the two existing dicts
rather than re-transcribing them.

Two vocabularies:

  relative_path  under the static-resources root, e.g. "grids/maskGlob1km.gds".
                 This is what LANDICE_STATIC_RELATIVE_PATHS /
                 MRVA_STATIC_RELATIVE_PATHS / seasonal_relative_path() produce,
                 and therefore exactly what both orchestrators join against
                 their root to build a local path or an s3:// href.
  source path    where the bytes live on the production host today.

Case is load-bearing throughout (maskGLOBp01deg vs maskGlob1km vs MUR25grid vs
CylinderP01_edge): S3 keys are case-sensitive. Always key off these tables,
never off a directory listing.
"""
import dataclasses
import os
import pathlib
from typing import Iterator, List, Optional

from landice_static_files import LANDICE_STATIC_RELATIVE_PATHS
from mrva_static_files import MRVA_STATIC_RELATIVE_PATHS, seasonal_relative_path

# Production source locations, matching utils/bundle_prod_static.sh's env-var
# contract so the two stay interchangeable.
PROD_DEFAULTS = {
    "GRIDS_DIR": "/home/tmchin/grids",
    "ICE_DIR": "/home/tmchin/ice",
    "SEASONAL_DIR": "/home/tmchin/nas/seasonal",
    "POLARCAP_FILE": "/nas2/landice/CylinderP01_edge.bip",
}

SEASONAL_DAYS = 365  # mur_001.nc .. mur_365.nc; doy 366 folds onto 365

# Regeneratable from the four tiny generator inputs below, but shipped anyway:
# regeneration needs licensed MATLAB (never available on MAAP), and regenerated
# nearest-neighbour index matrices would not be bit-identical to production's,
# which would shift landice output and break every truth-data comparison for a
# reason unrelated to this migration.
_GENERATOR_INPUTS = [
    "mat/landindexNH.mat",
    "mat/landindexSH.mat",
    "mat/latlonOSISAFnh.mat",
    "mat/latlonOSISAFsh.mat",
]

# Present in the prod tree but deliberately NOT uploaded:
#   grids/Glob1km.mask     ~1 GB, no live code path references it
#   grids/maskGlob8km.gds  only reachable via a csp2nc4a.m fallback; likely dead
#   seasonal25/            undocumented; reachability unconfirmed
EXCLUDED = ("grids/Glob1km.mask", "grids/maskGlob8km.gds", "seasonal25/")


@dataclasses.dataclass(frozen=True)
class Entry:
    """One file to stage, and where it comes from."""
    relative_path: str          # under the static-resources root
    source: pathlib.Path        # where it lives now
    required: bool              # a run cannot proceed without it
    group: str                  # "grids" | "mat" | "seasonal" | "landice" | "optional"

    @property
    def exists(self) -> bool:
        return self.source.is_file()


def _prod_source(relative_path: str, env: dict) -> pathlib.Path:
    """Map a static-resources relative path back to its production location.

    Mirrors bundle_prod_static.sh, including its legacy p011 fallback: older
    deployments put the p011 saf2 pair at the top level of ICE_DIR rather than
    in a p011/ subdirectory. Dropping that fallback silently skips two 121 MB
    files.
    """
    grids = pathlib.Path(env["GRIDS_DIR"])
    ice = pathlib.Path(env["ICE_DIR"])
    seasonal = pathlib.Path(env["SEASONAL_DIR"])

    if relative_path == "landice/CylinderP01_edge.bip":
        return pathlib.Path(env["POLARCAP_FILE"])
    if relative_path.startswith("grids/"):
        return grids / relative_path[len("grids/"):]
    if relative_path.startswith("seasonal/"):
        return seasonal / relative_path[len("seasonal/"):]
    if relative_path.startswith("mat/"):
        rest = relative_path[len("mat/"):]
        candidate = ice / rest
        if not candidate.is_file() and rest.startswith("p011/"):
            legacy = ice / rest[len("p011/"):]
            if legacy.is_file():
                return legacy
        return candidate
    raise ValueError(f"no production source known for {relative_path!r}")


def iter_entries(
    *,
    source_root: Optional[os.PathLike] = None,
    prod_env: Optional[dict] = None,
    include_optional: bool = False,
    include_seasonal: bool = True,
    seasonal_doys: Optional[List[int]] = None,
) -> Iterator[Entry]:
    """Yield every file to stage, deterministically ordered.

    Exactly one of `source_root` (a static-resources/-shaped tree) or
    `prod_env` (the scattered production layout) selects where sources come
    from; `prod_env` defaults to PROD_DEFAULTS overlaid with os.environ.
    """
    if source_root is not None:
        root = pathlib.Path(source_root)
        def resolve(rel):
            return root / rel
    else:
        # Precedence, lowest to highest: built-in defaults, the environment
        # (same variable names bundle_prod_static.sh honours), explicit args.
        env = dict(PROD_DEFAULTS)
        for key in PROD_DEFAULTS:
            if os.environ.get(key):
                env[key] = os.environ[key]
        env.update({k: v for k, v in (prod_env or {}).items() if v})

        def resolve(rel):
            return _prod_source(rel, env)

    # landice's six, deduplicated and sorted so the plan is reproducible
    for rel in sorted(set(LANDICE_STATIC_RELATIVE_PATHS.values())):
        group = "grids" if rel.startswith("grids/") else "mat"
        yield Entry(rel, resolve(rel), required=True, group=group)

    # mrva's fixed statics. MUR25grid is optional -- absent means "skip MUR25
    # product generation", which mrva/bin/entrypoint.sh handles explicitly.
    for name, rel in sorted(MRVA_STATIC_RELATIVE_PATHS.items()):
        required = name != "mur25_grid"
        group = "landice" if rel.startswith("landice/") else "grids"
        yield Entry(rel, resolve(rel), required=required, group=group)

    if include_seasonal:
        doys = seasonal_doys if seasonal_doys is not None else range(1, SEASONAL_DAYS + 1)
        for doy in doys:
            rel = seasonal_relative_path(doy)
            yield Entry(rel, resolve(rel), required=True, group="seasonal")

    if include_optional:
        for rel in _GENERATOR_INPUTS:
            yield Entry(rel, resolve(rel), required=False, group="optional")


def expected_relative_paths(**kwargs) -> List[str]:
    """Just the relative paths, for comparing against a bucket listing."""
    return [e.relative_path for e in iter_entries(**kwargs)]
