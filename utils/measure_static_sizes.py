"""Measure the on-disk size of every static / semi-static reference file the
MUR containerized pipeline touches, and report which of them could instead
be regenerated at build time from much smaller source files.

Background: docs/static-data.html establishes which
files are actually live (reachable from the compiled container entry points).
Reading the generator scripts under landice/data_creation/ shows that four of
the six landice static files (the saf2north.mat/saf2south.mat pairs) and
MRVA's CylinderP01_edge.bip are *derived* data -- they're reproducible from
the land masks (already required) plus a handful of tiny OSI-SAF index files,
via landice/data_creation/{p01,p011}/saf2{north,south}.m (nearest.f-
accelerated) and landice/data_creation/p01/makeedge.m (pure constants, no
input files at all). This script quantifies exactly how much shipping those
precomputed files costs vs. shipping only their small inputs.

Two ways to point this at your data, depending on which machine you're on:

1. **A single static-resources root** (the engineering/container test host,
   or any layout matching docs/static-data.html's
   static-resources/{grids,mat,seasonal,landice}/... structure -- this is
   what config.json's landice.static_resources_dir /
   mrva.static_resources_dir points at):

       python utils/measure_static_sizes.py --root /data3/jleach/mur/testing/static-resources
       STATIC_RESOURCES_ROOT=/data3/jleach/mur/testing/static-resources \\
           python utils/measure_static_sizes.py

   This derives GRIDS_DIR=<root>/grids, ICE_DIR=<root>/mat,
   SEASONAL_DIR=<root>/seasonal, POLARCAP_FILE=<root>/landice/CylinderP01_edge.bip,
   L4_DIR=<root>/L4, SEASONAL25_DIR=<root>/seasonal25.

   If you don't know the root on your engineering host, find it with:
       find /data3 /data1 -maxdepth 4 \\( -iname static-resources -o -iname maskGLOBp01deg.gds \\) 2>/dev/null

2. **Individual source-root env vars** (the production/ops host layout,
   same variables as bundle_prod_static.sh -- files live scattered across
   /home/tmchin/grids, /home/tmchin/ice, etc., not under one root):

       python utils/measure_static_sizes.py   # defaults to production paths
       GRIDS_DIR=/alt/grids ICE_DIR=/alt/ice python utils/measure_static_sizes.py

   Individual env vars always win over --root/STATIC_RESOURCES_ROOT for
   whichever ones you set, so you can mix both (e.g. a root plus one override).

Dry run against the local test fixtures (no prod/engineering mounts needed):

    python utils/measure_static_sizes.py --root landice/tests/in
"""

import argparse
import json
import os


def env(name, default=None):
    return os.environ.get(name, default)


def resolve_paths(root):
    """Compute the six source-root globals from an optional static-resources
    root (matching docs/static-data.html's layout) plus individual
    env-var overrides, which always win. Falls back to production-host
    defaults when neither a root nor an override is given."""
    global GRIDS_DIR, ICE_DIR, SEASONAL_DIR, SEASONAL25_DIR, POLARCAP_FILE, L4_DIR

    if root:
        default_grids = os.path.join(root, "grids")
        default_ice = os.path.join(root, "mat")
        default_seasonal = os.path.join(root, "seasonal")
        default_seasonal25 = os.path.join(root, "seasonal25")
        default_polarcap = os.path.join(root, "landice", "CylinderP01_edge.bip")
        default_l4 = os.path.join(root, "L4")
    else:
        default_grids = "/home/tmchin/grids"
        default_ice = "/home/tmchin/ice"
        default_seasonal = "/home/tmchin/nas/seasonal"
        default_seasonal25 = "/home/tmchin/nas/seasonal25"
        default_polarcap = "/nas2/landice/CylinderP01_edge.bip"
        default_l4 = "/store/ghrsst/open/data/L4"

    GRIDS_DIR = env("GRIDS_DIR", default_grids)
    ICE_DIR = env("ICE_DIR", default_ice)
    SEASONAL_DIR = env("SEASONAL_DIR", default_seasonal)
    SEASONAL25_DIR = env("SEASONAL25_DIR", default_seasonal25)
    POLARCAP_FILE = env("POLARCAP_FILE", default_polarcap)
    L4_DIR = env("L4_DIR", default_l4)


GRIDS_DIR = ICE_DIR = SEASONAL_DIR = SEASONAL25_DIR = POLARCAP_FILE = L4_DIR = None


def stat_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def ice_mat_path(res, fname):
    """Mirrors bundle_prod_static.sh's p011-legacy-fallback lookup."""
    subdir_path = os.path.join(ICE_DIR, res, fname)
    if os.path.isfile(subdir_path):
        return subdir_path
    if res == "p011":
        legacy_path = os.path.join(ICE_DIR, fname)
        if os.path.isfile(legacy_path):
            return legacy_path
    return subdir_path  # missing; report as such


def scan_dir(dirpath, suffix):
    """Return (count, total_bytes, sizes) for files under dirpath ending in suffix."""
    if not os.path.isdir(dirpath):
        return 0, 0, []
    sizes = []
    for fname in os.listdir(dirpath):
        if fname.endswith(suffix):
            size = stat_size(os.path.join(dirpath, fname))
            if size is not None:
                sizes.append(size)
    return len(sizes), sum(sizes), sizes


def human(n):
    if n is None:
        return "MISSING"
    f = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if f < 1024 or unit == "GiB":
            return f"{f:.1f}{unit}"
        f /= 1024
    return f"{f:.1f}TiB"


def report_group(title, entries, note=None):
    """entries: list of (label, path). Returns (found_bytes, missing_labels)."""
    print(f"\n[{title}]")
    if note:
        print(f"  # {note}")
    total = 0
    missing = []
    for label, path in entries:
        size = stat_size(path)
        if size is None:
            missing.append(label)
            print(f"  MISS  {label:32s} {path}")
        else:
            total += size
            print(f"  {human(size):>10s}  {label:32s} {path}")
    print(f"  subtotal: {human(total)} ({total:,} bytes)")
    return total, missing


def main():
    parser = argparse.ArgumentParser(
        description="Measure on-disk sizes of MUR static/semi-static reference data"
    )
    parser.add_argument("--root", type=str, default=env("STATIC_RESOURCES_ROOT"),
                        help="Static-resources root laid out per docs/static-data.html "
                             "(root/{grids,mat,seasonal,landice}/...). Defaults to "
                             "$STATIC_RESOURCES_ROOT, then to production-host paths "
                             "if neither is given. Individual *_DIR / *_FILE env "
                             "vars always override whatever this derives.")
    parser.add_argument("--json", type=str, default=None,
                        help="Also write a machine-readable size report to this path")
    args = parser.parse_args()

    resolve_paths(args.root)

    print("MUR Static Data Size Report")
    print("=" * 60)
    if args.root:
        print(f"  --root         = {args.root}")
    print(f"  GRIDS_DIR      = {GRIDS_DIR}")
    print(f"  ICE_DIR        = {ICE_DIR}")
    print(f"  SEASONAL_DIR   = {SEASONAL_DIR}")
    print(f"  SEASONAL25_DIR = {SEASONAL25_DIR}")
    print(f"  POLARCAP_FILE  = {POLARCAP_FILE}")
    print(f"  L4_DIR         = {L4_DIR}")

    result = {}

    # -- Landice's 6 required files: no generator, must ship as precomputed --
    landmasks = [
        ("grids/maskGLOBp01deg.gds", os.path.join(GRIDS_DIR, "maskGLOBp01deg.gds")),
        ("grids/maskGlob1km.gds", os.path.join(GRIDS_DIR, "maskGlob1km.gds")),
    ]
    landmasks_bytes, landmasks_missing = report_group(
        "Land masks (irreducible floor -- no generator exists anywhere in this codebase)",
        landmasks,
    )
    result["land_masks"] = {"bytes": landmasks_bytes, "missing": landmasks_missing}

    saf_precomputed = [
        ("mat/p01/saf2north.mat", ice_mat_path("p01", "saf2north.mat")),
        ("mat/p01/saf2south.mat", ice_mat_path("p01", "saf2south.mat")),
        ("mat/p011/saf2north.mat", ice_mat_path("p011", "saf2north.mat")),
        ("mat/p011/saf2south.mat", ice_mat_path("p011", "saf2south.mat")),
    ]
    saf_bytes, saf_missing = report_group(
        "OSI-SAF index matrices (regeneratable -- see 'generator inputs' below)",
        saf_precomputed,
        note="landice/data_creation/{p01,p011}/saf2{north,south}.m reproduces these "
             "from the land masks above + the tiny inputs below.",
    )
    result["saf_precomputed"] = {"bytes": saf_bytes, "missing": saf_missing}

    # -- Small inputs that regenerate the saf2*.mat files above --
    saf_inputs = [
        ("mat/landindexNH.mat", os.path.join(ICE_DIR, "landindexNH.mat")),
        ("mat/landindexSH.mat", os.path.join(ICE_DIR, "landindexSH.mat")),
        ("mat/latlonOSISAFnh.mat", os.path.join(ICE_DIR, "latlonOSISAFnh.mat")),
        ("mat/latlonOSISAFsh.mat", os.path.join(ICE_DIR, "latlonOSISAFsh.mat")),
    ]
    saf_inputs_bytes, saf_inputs_missing = report_group(
        "Generator inputs for the OSI-SAF matrices above",
        saf_inputs,
    )
    result["saf_generator_inputs"] = {"bytes": saf_inputs_bytes, "missing": saf_inputs_missing}

    # -- CylinderP01_edge.bip: needs zero external inputs, pure formula --
    edge_bytes, edge_missing = report_group(
        "Polar cap edge (regeneratable -- makeedge.m needs ZERO input files)",
        [("landice/CylinderP01_edge.bip", POLARCAP_FILE)],
    )
    result["polar_cap_edge"] = {"bytes": edge_bytes, "missing": edge_missing}

    # -- MRVA's other required static files --
    mrva_extra = [
        ("grids/MUR25grid.gds", os.path.join(GRIDS_DIR, "MUR25grid.gds")),
    ]
    mrva_extra_bytes, mrva_extra_missing = report_group(
        "MRVA additional required files", mrva_extra
    )
    result["mrva_extra"] = {"bytes": mrva_extra_bytes, "missing": mrva_extra_missing}

    # -- Seasonal climatology: real computed data, not regeneratable --
    print("\n[Seasonal climatology (required -- real multi-year averaged data, "
          "no smaller source exists)]")
    seasonal_count, seasonal_bytes, seasonal_sizes = scan_dir(SEASONAL_DIR, ".nc")
    if seasonal_count:
        avg = seasonal_bytes / seasonal_count
        print(f"  {seasonal_count} files (expected 365), "
              f"total {human(seasonal_bytes)} ({seasonal_bytes:,} bytes), "
              f"avg {human(avg)}/file, "
              f"min {human(min(seasonal_sizes))}, max {human(max(seasonal_sizes))}")
        if seasonal_count != 365:
            print(f"  WARNING: expected 365 files, found {seasonal_count}")
    else:
        print(f"  MISS  no mur_*.nc files found under {SEASONAL_DIR}")
    result["seasonal"] = {
        "count": seasonal_count,
        "bytes": seasonal_bytes,
        "expected_count": 365,
    }

    # -- Optional / unconfirmed --
    print("\n[Optional / unconfirmed -- not required by the live container code paths]")

    glob1km_mask_size = stat_size(os.path.join(GRIDS_DIR, "Glob1km.mask"))
    print(f"  {human(glob1km_mask_size):>10s}  grids/Glob1km.mask "
          f"(not referenced by any live container code path; skip)")

    mask8km_size = stat_size(os.path.join(GRIDS_DIR, "maskGlob8km.gds"))
    print(f"  {human(mask8km_size):>10s}  grids/maskGlob8km.gds "
          f"(only reached by csp2nc4a.m's unrecognized-version fallback branch; "
          f"likely dead -- confirm before shipping)")

    seasonal25_count, seasonal25_bytes, _ = scan_dir(SEASONAL25_DIR, ".mat")
    print(f"  {seasonal25_count} files, {human(seasonal25_bytes)}  seasonal25/*.mat "
          f"(undocumented in docs/static-data.html; confirm whether makeMUR25_container.m's "
          f"seasonal25 path is actually reachable before including)")

    l4_count = 0
    l4_bytes = 0
    if os.path.isdir(L4_DIR):
        for root, _, files in os.walk(L4_DIR):
            for fname in files:
                if fname.endswith(".bz2"):
                    size = stat_size(os.path.join(root, fname))
                    if size is not None:
                        l4_count += 1
                        l4_bytes += size
    print(f"  {l4_count} files, {human(l4_bytes)}  L4/**/*.bz2 "
          f"(optional -- only used as trimbip3a.m's fallback when no prior-day "
          f".c06 coefficient exists; not needed for steady-state runs)")

    result["optional"] = {
        "glob1km_mask_bytes": glob1km_mask_size,
        "maskGlob8km_bytes": mask8km_size,
        "seasonal25": {"count": seasonal25_count, "bytes": seasonal25_bytes},
        "l4": {"count": l4_count, "bytes": l4_bytes},
    }

    # -- Totals --
    print("\n" + "=" * 60)
    print("TOTALS")

    floor = landmasks_bytes + mrva_extra_bytes
    full_precomputed = floor + saf_bytes + edge_bytes
    optimized = floor + saf_inputs_bytes  # edge_bytes dropped: zero-input generator
    grand_full = full_precomputed + seasonal_bytes
    grand_optimized = optimized + seasonal_bytes

    print(f"  Irreducible floor (land masks + MUR25grid, no generator exists):"
          f" {human(floor)}")
    print(f"  + saf2*.mat + edge shipped precomputed (no build-time generation):"
          f" {human(full_precomputed)}")
    print(f"  + saf2*.mat + edge regenerated at build time (ship tiny inputs instead):"
          f" {human(optimized)}")
    print(f"  Savings from build-time regeneration: {human(full_precomputed - optimized)}")
    print()
    print(f"  Grand total, ship-everything-precomputed + seasonal: {human(grand_full)}")
    print(f"  Grand total, optimized (regenerate saf2*/edge) + seasonal: {human(grand_optimized)}")

    result["totals"] = {
        "floor_bytes": floor,
        "full_precomputed_bytes": full_precomputed,
        "optimized_bytes": optimized,
        "grand_total_full_bytes": grand_full,
        "grand_total_optimized_bytes": grand_optimized,
    }

    if args.json:
        with open(args.json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
