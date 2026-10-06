"""Profile the seasonal climatology files (seasonal/mur_###.nc, ~396MB/file
average, ~141GB total measured across all 365) to test two ways of shrinking
the archive before deciding how to distribute it: (1) delta-encoding against
the previous day, and (2) restacking all days into a single time-chunked
"cube" (NetCDF4/HDF5 style: chunk shape (n_days, small_y, small_x) + byte
shuffle) so the compressor can exploit each pixel's smooth day-of-year
time series directly, instead of compressing 365 independent spatial
snapshots that never see each other.

No generator for these files exists anywhere in this codebase or
mur-internal/ -- unlike the OSI-SAF matrices or CylinderP01_edge.bip, this is
genuinely external derived data (docs/static-data.html: "Generated from multi-year
MUR SST archive"). This script can't shrink that fact; it measures whether
re-encoding what's already on disk buys real savings, using the same raw
packed representation readSeasonal.m reads (int16 mean_sst/standard_deviation
with scale_factor/add_offset -- see mrva/src/matlab/io/readSeasonal.m:60-83).

Note on interpreting the cube test: it uses a spatial tile (not the full
36000x17999 grid) and only the sampled days below (not a real 365-length
time axis), for speed/memory -- it estimates the *ratio* a real cube would
achieve, not the exact total-archive size. A real cube, if the ratio looks
good, would be built once (offline, from all 365 files) using
netCDF4.Dataset(..., format="NETCDF4").createVariable(chunksizes=(365, y, x),
zlib=True, shuffle=True) and unpacked back into 365 files at container build
time -- readSeasonal.m itself would never need to change.

Run on the engineering host, against a handful of real files including at
least one adjacent day-of-year pair (to test diffing) spread across seasons:

    python utils/profile_seasonal_climatology.py --dir /data3/.../seasonal
    python utils/profile_seasonal_climatology.py --dir /data3/.../seasonal \\
        --doys 1 2 91 92 182 183 273 274 365
"""

import argparse
import os
import zlib

import netCDF4
import numpy as np

try:
    import zstandard
    HAVE_ZSTD = True
except ImportError:
    HAVE_ZSTD = False


def file_path(seasonal_dir, doy):
    return os.path.join(seasonal_dir, f"mur_{doy:03d}.nc")


def describe_file(ds, size_bytes):
    print(f"  file size: {size_bytes:,} bytes ({size_bytes / 1024 / 1024:.1f} MiB)")
    for name, var in ds.variables.items():
        filters = var.filters() if hasattr(var, "filters") else None
        chunking = var.chunking() if hasattr(var, "chunking") else None
        print(f"  var {name}: shape={var.shape} dtype={var.dtype} "
              f"chunking={chunking} filters={filters}")


def load_raw(ds, varname):
    """Raw on-disk packed values (int16 typically), scale/offset NOT applied --
    this is what actually gets written to disk, so it's what we should diff."""
    var = ds.variables[varname]
    var.set_auto_maskandscale(False)
    return np.asarray(var[:])


def shuffle_bytes(arr):
    """Mimic HDF5's byte-shuffle filter: regroup bytes by significance (all
    high bytes together, then all low bytes, etc.) so deflate/zstd sees long
    runs of slowly-changing bytes instead of interleaved item boundaries.
    This is the other half of the standard HDF5 filter chain (shuffle+zlib) --
    and the production seasonal files already use shuffle=True (see the
    `filters=` line each file prints), so any baseline that skips this step
    is NOT a fair comparison against them."""
    itemsize = arr.dtype.itemsize
    flat = np.ascontiguousarray(arr).view(np.uint8).reshape(-1, itemsize)
    return flat.T.copy().tobytes()


def compressed_size(arr, label, level=6, shuffle=False):
    raw = shuffle_bytes(arr) if shuffle else arr.tobytes()
    zlib_size = len(zlib.compress(raw, level=level))
    tag = "shuffle+zlib" if shuffle else "zlib (unshuffled, NOT comparable to the real files)"
    line = f"    {label}: raw {len(raw):,}B -> {tag} {zlib_size:,}B ({zlib_size / len(raw) * 100:.1f}%)"
    if HAVE_ZSTD:
        zstd_size = len(zstandard.ZstdCompressor(level=19).compress(raw))
        ztag = "shuffle+zstd-19" if shuffle else "zstd-19 (unshuffled)"
        line += f", {ztag} {zstd_size:,}B ({zstd_size / len(raw) * 100:.1f}%)"
    else:
        zstd_size = None
    print(line)
    return zlib_size, zstd_size


def cube_compression_test(raw_arrays, doys_sorted, varname, tile=2000, level=6):
    """Compare per-day-independent compression against time-major "cube"
    compression on a spatial tile, to estimate whether restacking the whole
    archive into one time-chunked file would help. See module docstring for
    caveats (tile subsample + sparse day sample, not the real full cube).

    The per-day SHUFFLED baseline is the fair comparison -- it's the same
    filter chain (shuffle+zlib) the real files already use. The unshuffled
    baseline is printed only for transparency/context, not as the number to
    judge the cube against."""
    days_with_var = [d for d in doys_sorted if varname in raw_arrays.get(d, {})]
    if len(days_with_var) < 2:
        return
    sample = raw_arrays[days_with_var[0]][varname]
    ny, nx = sample.shape
    ty, tx = min(tile, ny), min(tile, nx)
    y0, x0 = (ny - ty) // 2, (nx - tx) // 2
    stack = np.stack([raw_arrays[d][varname][y0:y0 + ty, x0:x0 + tx] for d in days_with_var])

    per_day_zlib = sum(len(zlib.compress(stack[i].tobytes(), level=level))
                        for i in range(len(days_with_var)))
    per_day_shuffled_zlib = sum(len(zlib.compress(shuffle_bytes(stack[i]), level=level))
                                 for i in range(len(days_with_var)))

    # Transpose so each pixel's day-of-year series is contiguous -- this is
    # what a chunk shaped (n_days, small_y, small_x) looks like on disk.
    cube = np.ascontiguousarray(np.transpose(stack, (1, 2, 0)))  # (ty, tx, n_days)
    cube_zlib = len(zlib.compress(cube.tobytes(), level=level))
    cube_shuffle_zlib = len(zlib.compress(shuffle_bytes(cube), level=level))

    print(f"\n  cube test: tile {ty}x{tx}, {len(days_with_var)} sampled days "
          f"(doy {days_with_var}), var {varname}")
    print(f"    per-day, unshuffled (zlib):         {per_day_zlib:,}B  (context only, NOT the real baseline)")
    print(f"    per-day, shuffle+zlib (FAIR BASELINE, matches real files): {per_day_shuffled_zlib:,}B")
    print(f"    time-major cube, unshuffled (zlib): {cube_zlib:,}B  "
          f"({cube_zlib / per_day_shuffled_zlib * 100:.1f}% of fair baseline)")
    print(f"    time-major cube + shuffle (zlib):   {cube_shuffle_zlib:,}B  "
          f"({cube_shuffle_zlib / per_day_shuffled_zlib * 100:.1f}% of fair baseline)  <- key number")
    if HAVE_ZSTD:
        cube_zstd = len(zstandard.ZstdCompressor(level=19).compress(cube.tobytes()))
        cube_shuffle_zstd = len(zstandard.ZstdCompressor(level=19).compress(shuffle_bytes(cube)))
        print(f"    time-major cube (zstd-19):          {cube_zstd:,}B  "
              f"({cube_zstd / per_day_shuffled_zlib * 100:.1f}% of fair baseline)")
        print(f"    time-major cube + shuffle (zstd-19): {cube_shuffle_zstd:,}B  "
              f"({cube_shuffle_zstd / per_day_shuffled_zlib * 100:.1f}% of fair baseline)  <- key number")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", required=True,
                        help="seasonal/ directory containing mur_###.nc")
    parser.add_argument("--doys", type=int, nargs="+",
                        default=[1, 2, 91, 92, 182, 183, 273, 274, 365],
                        help="Day-of-year samples to profile; include adjacent "
                             "pairs (e.g. 1 2) to test diffing across seasons")
    parser.add_argument("--vars", nargs="+", default=["mean_sst", "standard_deviation"],
                        help="Variable names to profile (defaults match readSeasonal.m)")
    parser.add_argument("--tile", type=int, default=2000,
                        help="Spatial tile size (pixels per side) for the cube "
                             "compression test -- full grid would be too slow "
                             "for a quick profiling run")
    parser.add_argument("--level", type=int, default=3,
                        help="zlib compression level for the full-grid absolute/"
                             "diff sections (default 3, fast -- these compress "
                             "~1.2GiB arrays repeatedly so high levels are slow; "
                             "only relative ratios matter for the decision, not "
                             "absolute best-case size). The cube test's tile is "
                             "small enough to always use this same level quickly.")
    args = parser.parse_args()

    print("Seasonal climatology profile")
    print("=" * 60)
    if not HAVE_ZSTD:
        print("(zstandard not installed -- only zlib ratios shown; "
              "pip install zstandard for a closer real-world comparison)")

    raw_arrays = {}  # doy -> {varname: raw int16 array}
    real_file_bytes = {}  # doy -> on-disk file size (all variables combined)
    for doy in args.doys:
        path = file_path(args.dir, doy)
        if not os.path.isfile(path):
            print(f"\n[doy {doy:03d}] MISSING: {path}")
            continue
        size_bytes = os.path.getsize(path)
        real_file_bytes[doy] = size_bytes
        print(f"\n[doy {doy:03d}] {path}")
        with netCDF4.Dataset(path) as ds:
            describe_file(ds, size_bytes)
            raw_arrays[doy] = {}
            for varname in args.vars:
                if varname in ds.variables:
                    raw_arrays[doy][varname] = load_raw(ds, varname)

    doys_sorted = sorted(raw_arrays)
    if real_file_bytes:
        avg_real = sum(real_file_bytes.values()) / len(real_file_bytes)
        print(f"\n[Ground truth] real on-disk file size (all variables combined, "
              f"already shuffle+zlib complevel=7): avg {avg_real:,.0f}B "
              f"({avg_real / 1024 / 1024:.1f} MiB/file) across {len(real_file_bytes)} sampled files")
        print("This is the number any alternative encoding has to beat -- it's "
              "already well-compressed, so don't judge results against a naive "
              "unshuffled baseline (see below).")

    print(f"\n[Absolute-field compression baseline] (--level {args.level})")
    abs_shuffled_sizes = {}
    for doy in doys_sorted:
        for varname, arr in raw_arrays[doy].items():
            compressed_size(arr, f"doy {doy:03d} {varname}", level=args.level, shuffle=False)
            zlib_shuf, _ = compressed_size(arr, f"doy {doy:03d} {varname}", level=args.level, shuffle=True)
            abs_shuffled_sizes[(doy, varname)] = zlib_shuf

    print("\n[Delta-encoding test: adjacent-day diffs, same variable]")
    for a, b in zip(doys_sorted, doys_sorted[1:]):
        for varname in args.vars:
            arr_a = raw_arrays.get(a, {}).get(varname)
            arr_b = raw_arrays.get(b, {}).get(varname)
            if arr_a is None or arr_b is None or arr_a.shape != arr_b.shape:
                continue
            print(f"\n  doy {a:03d} -> doy {b:03d}  ({varname})")
            diff = arr_b.astype(np.int32) - arr_a.astype(np.int32)
            print(f"    diff range: [{diff.min()}, {diff.max()}], "
                  f"mean abs diff: {np.abs(diff).mean():.2f} (packed int units)")
            diff_i16 = np.clip(diff, -32768, 32767).astype(np.int16)
            diff_zlib, _ = compressed_size(diff_i16, f"doy {a:03d}->{b:03d} {varname} (diff, shuffled)",
                                            level=args.level, shuffle=True)
            fair_baseline = abs_shuffled_sizes.get((b, varname))
            if fair_baseline:
                print(f"    diff/fair-baseline ratio (shuffle+zlib): "
                      f"{diff_zlib / fair_baseline * 100:.1f}%  <- key number")

    print("\n[Cube test: time-major chunking vs. independent per-day compression]")
    for varname in args.vars:
        cube_compression_test(raw_arrays, doys_sorted, varname, tile=args.tile, level=args.level)

    print("\nDone. Compare the two sections above:")
    print("  - Delta-encoding ratios well under 100% -> diffing against the")
    print("    previous day helps.")
    print("  - Cube ratios well under 100% (and lower than the delta-encoding")
    print("    ratios) -> restacking into one time-chunked NetCDF4/HDF5 file")
    print("    captures more redundancy than simple diffing and is the better")
    print("    lever to build into the bundling script.")
    print("  - Both close to 100% -> the fields are already near-incompressible")
    print("    day-to-day and ~141GB is closer to a hard floor for this data;")
    print("    move it to object storage rather than trying to shrink it further.")


if __name__ == "__main__":
    main()
