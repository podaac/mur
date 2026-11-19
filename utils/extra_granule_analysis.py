#!/usr/bin/env python3
"""Pull the DOY-163 MODIS granules the container ingested but production didn't,
then analyze them: SST distribution, day vs night fraction, and how many pixels
the MRVA quality filter keeps vs. what each granule provides.

The "extra" granule set is recomputed from the L2Plist_*.txt files in
prod_data/ and container_data/ (basename diff, container - prod), so it stays in
sync with whatever snapshots are on disk.

Filtering matches the pipeline exactly: l2p2bic.m keeps pixels where
quality_level >= minConfValue (5 for MODISA/MODIST, per SensorTable.m). A pixel
is "provided" if its sea_surface_temperature is not the _FillValue; it is "kept"
if additionally quality_level >= threshold.

Day/night is taken from the granule filename token (-D- / -N-) and cross-checked
against the l2p_flags "day" bit inside the granule.

Usage:
    # 1. Download the extra granules (needs Earthdata creds in ~/.netrc)
    .venv/bin/python utils/extra_granule_analysis.py download

    # 2. Analyze + plot
    .venv/bin/python utils/extra_granule_analysis.py analyze
"""

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROD = REPO / "prod_data"
CONT = REPO / "container_data"
OUTDIR = CONT / "extra_day163"            # where granules land
YEAR = 2026
DOYS = [162, 163, 164, 165]               # ±2 window around analysis day 164

# sensor -> (CMR short_name, quality threshold from SensorTable.m)
SENSORS = {
    "MODISA": ("MODIS_A-JPL-L2P-v2019.0", 5),
    "MODIST": ("MODIS_T-JPL-L2P-v2019.0", 5),
}


def l2plist_basenames(root, sensor, doy):
    f = root / "bic" / sensor / str(YEAR) / f"L2Plist_Global_{sensor}_{YEAR}_{doy:03d}.txt"
    if not f.exists():
        return None
    out = set()
    for line in f.read_text().splitlines():
        line = line.strip()
        if line:
            out.add(os.path.basename(line))
    return out


def extra_granules():
    """Return {sensor: {doy: sorted([basenames only in container])}} (non-empty only)."""
    result = {}
    for sensor in SENSORS:
        for doy in DOYS:
            p = l2plist_basenames(PROD, sensor, doy) or set()
            c = l2plist_basenames(CONT, sensor, doy) or set()
            only_c = sorted(c - p)
            if only_c:
                result.setdefault(sensor, {})[doy] = only_c
    return result


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------
PODAAC = "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected"


def cmd_download(args):
    import time
    import requests

    OUTDIR.mkdir(parents=True, exist_ok=True)
    extras = extra_granules()
    session = requests.Session()       # honors ~/.netrc for Earthdata auth

    n_ok = n_fail = n_skip = 0
    for sensor, by_doy in extras.items():
        short_name, _ = SENSORS[sensor]
        names = sorted({n for lst in by_doy.values() for n in lst})
        print(f"{sensor}: {len(names)} extra granules to fetch from {short_name}")
        for name in names:
            dest = OUTDIR / name
            if dest.exists() and dest.stat().st_size > 0:
                n_skip += 1
                continue
            url = f"{PODAAC}/{short_name}/{name}"
            ok = False
            for attempt in range(4):
                try:
                    with session.get(url, stream=True, timeout=600) as resp:
                        resp.raise_for_status()
                        tmp = dest.with_suffix(dest.suffix + ".part")
                        with open(tmp, "wb") as fh:
                            for chunk in resp.iter_content(chunk_size=1 << 20):
                                fh.write(chunk)
                        tmp.rename(dest)
                    mb = dest.stat().st_size / 1024**2
                    print(f"  OK {name} ({mb:.1f} MB)")
                    ok = True
                    break
                except Exception as ex:
                    print(f"  retry {attempt+1}/4 {name}: {type(ex).__name__} {str(ex)[:80]}")
                    if dest.with_suffix(dest.suffix + ".part").exists():
                        dest.with_suffix(dest.suffix + ".part").unlink()
                    time.sleep(2 * (attempt + 1))
            if ok:
                n_ok += 1
            else:
                n_fail += 1
                print(f"  FAIL {name}")

    print(f"\nDownload summary: ok={n_ok} skip(existing)={n_skip} fail={n_fail}")
    print(f"Granules in: {OUTDIR}")


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------
def day_night_from_name(name):
    # ...-MODIS_A-D-... or ...-MODIS_T-N-...
    if "-D-" in name:
        return "day"
    if "-N-" in name:
        return "night"
    return "unknown"


def cmd_analyze(args):
    import numpy as np
    import netCDF4
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    extras = extra_granules()
    files = []  # (sensor, threshold, basename, path)
    for sensor, by_doy in extras.items():
        _, thr = SENSORS[sensor]
        seen = set()
        for doy, lst in by_doy.items():
            for name in lst:
                if name in seen:
                    continue
                seen.add(name)
                p = OUTDIR / name
                if p.exists():
                    files.append((sensor, thr, name, p))
                else:
                    print(f"  (not downloaded, skipping): {name}")

    if not files:
        print("No downloaded granules found. Run the 'download' subcommand first.")
        return

    # SST histogram bins (deg C)
    bins = np.arange(-2.0, 40.01, 0.25)
    centers = 0.5 * (bins[:-1] + bins[1:])
    hist = {("day", "kept"): np.zeros(len(centers)),
            ("night", "kept"): np.zeros(len(centers)),
            ("day", "filtered"): np.zeros(len(centers)),
            ("night", "filtered"): np.zeros(len(centers))}

    rows = []
    qhist_total = np.zeros(6, dtype=np.int64)  # quality_level 0..5 counts (kept-eligible)

    for sensor, thr, name, path in sorted(files):
        ds = netCDF4.Dataset(path)
        v = ds.variables["sea_surface_temperature"]
        raw = v[:]                       # netCDF4 applies scale/offset + mask by default
        # raw is a masked array in Kelvin; convert to degC, mask = fill
        sst_k = np.ma.filled(raw, np.nan).astype("float64").ravel()
        sst_c = sst_k - 273.15
        ql = np.ma.filled(ds.variables["quality_level"][:], -1).astype("int16").ravel()

        provided = np.isfinite(sst_c)            # non-fill SST
        kept = provided & (ql >= thr)
        filt = provided & ~kept

        dn = day_night_from_name(name)
        # cross-check with l2p_flags day bit if present
        day_bit_frac = None
        if "l2p_flags" in ds.variables:
            lf = np.ma.filled(ds.variables["l2p_flags"][:], 0).astype("int32").ravel()
            day_bit = _l2p_day_bit(ds.variables["l2p_flags"])
            if day_bit is not None:
                isday = (lf & day_bit) != 0
                kp = kept
                if kp.sum():
                    day_bit_frac = float(isday[kp].sum()) / float(kp.sum())

        # accumulate histograms (use filename day/night classification)
        cls = dn if dn in ("day", "night") else "day"
        if kept.any():
            hist[(cls, "kept")] += np.histogram(sst_c[kept], bins=bins)[0]
        if filt.any():
            hist[(cls, "filtered")] += np.histogram(sst_c[filt], bins=bins)[0]

        # quality-level tally over provided pixels
        for q in range(6):
            qhist_total[q] += int(((ql == q) & provided).sum())

        n_prov = int(provided.sum())
        n_kept = int(kept.sum())
        n_filt = int(filt.sum())
        sst_kept = sst_c[kept]
        # cheap content signature to detect duplicate-SST granules (same swath
        # published as both -D- and -N- at the terminator)
        sig = (n_prov, n_kept, int(np.nansum(sst_c[provided]) * 100))
        rows.append({
            "sensor": sensor, "name": name, "dn": dn,
            "provided": n_prov, "kept": n_kept, "filtered": n_filt,
            "keep_pct": (100.0 * n_kept / n_prov) if n_prov else 0.0,
            "sst_mean": float(np.mean(sst_kept)) if n_kept else float("nan"),
            "sst_std": float(np.std(sst_kept)) if n_kept else float("nan"),
            "day_bit_frac": day_bit_frac, "sig": sig,
        })
        ds.close()

    _report(rows, qhist_total)

    # ---- plot ----
    out_png = REPO / "extra_granules_day163_sst.png"
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    for cls, color in (("day", "tab:orange"), ("night", "tab:blue")):
        ax1.plot(centers, hist[(cls, "kept")], color=color, label=f"{cls} (kept)")
        ax1.plot(centers, hist[(cls, "filtered")], color=color, ls="--", alpha=0.5,
                 label=f"{cls} (filtered)")
    ax1.set_title("SST distribution of the 61 extra DOY-163 granules")
    ax1.set_xlabel("SST (deg C)"); ax1.set_ylabel("pixel count"); ax1.legend()

    # day vs night kept totals + filtered fraction bar
    day_kept = hist[("day", "kept")].sum()
    night_kept = hist[("night", "kept")].sum()
    day_filt = hist[("day", "filtered")].sum()
    night_filt = hist[("night", "filtered")].sum()
    labels = ["day", "night"]
    kept_vals = [day_kept, night_kept]
    filt_vals = [day_filt, night_filt]
    x = np.arange(2)
    ax2.bar(x, kept_vals, 0.5, label="kept (quality>=5)", color="tab:green")
    ax2.bar(x, filt_vals, 0.5, bottom=kept_vals, label="filtered", color="tab:red", alpha=0.7)
    ax2.set_xticks(x); ax2.set_xticklabels(labels)
    ax2.set_ylabel("pixel count"); ax2.set_title("Day vs night: kept vs filtered")
    ax2.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    print(f"\nPlot written: {out_png}")


def _l2p_day_bit(var):
    """Find the bit mask for 'day' in an l2p_flags variable's flag_meanings/flag_masks."""
    try:
        meanings = var.flag_meanings.split()
        masks = list(var.flag_masks)
    except Exception:
        return None
    for m, msk in zip(meanings, masks):
        if m.lower() == "day":
            return int(msk)
    return None


def _report(rows, qhist_total):
    print("\n" + "=" * 90)
    print("EXTRA DOY-163 GRANULE ANALYSIS (container - prod)")
    print("=" * 90)
    print(f"\n{'Sensor':<7} {'D/N':<6} {'Provided':>12} {'Kept':>12} {'Filtered':>12} "
          f"{'Keep%':>7} {'SST mean':>9}")
    print("-" * 90)
    for r in sorted(rows, key=lambda r: (r["sensor"], r["name"])):
        print(f"{r['sensor']:<7} {r['dn']:<6} {r['provided']:>12,} {r['kept']:>12,} "
              f"{r['filtered']:>12,} {r['keep_pct']:>6.1f}% {r['sst_mean']:>9.3f}")

    def agg(pred):
        prov = sum(r["provided"] for r in rows if pred(r))
        kept = sum(r["kept"] for r in rows if pred(r))
        filt = sum(r["filtered"] for r in rows if pred(r))
        return prov, kept, filt

    print("\n" + "=" * 90)
    print("TOTALS")
    print("=" * 90)
    for label, pred in (
        ("ALL", lambda r: True),
        ("MODISA", lambda r: r["sensor"] == "MODISA"),
        ("MODIST", lambda r: r["sensor"] == "MODIST"),
        ("day granules", lambda r: r["dn"] == "day"),
        ("night granules", lambda r: r["dn"] == "night"),
    ):
        prov, kept, filt = agg(pred)
        kp = (100.0 * kept / prov) if prov else 0.0
        fp = (100.0 * filt / prov) if prov else 0.0
        print(f"  {label:<16} provided={prov:>14,}  kept={kept:>14,} ({kp:5.1f}%)  "
              f"filtered={filt:>14,} ({fp:5.1f}%)")

    prov_all = sum(r["provided"] for r in rows)
    n_day = sum(1 for r in rows if r["dn"] == "day")
    n_night = sum(1 for r in rows if r["dn"] == "night")
    day_prov, day_kept, _ = agg(lambda r: r["dn"] == "day")
    kept_all = sum(r["kept"] for r in rows)
    print(f"\n  Granules: {n_day} day, {n_night} night")
    if prov_all:
        print(f"  Daylight share of provided pixels: {100.0*day_prov/prov_all:.1f}%")
    if kept_all:
        print(f"  Daylight share of KEPT pixels:     {100.0*day_kept/kept_all:.1f}%")

    # duplicate-SST granules (same swath published as both -D- and -N-)
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[r["sig"]].append(r)
    dups = [g for g in groups.values() if len(g) > 1]
    if dups:
        dup_prov = sum(r["provided"] for g in dups for r in g[1:])
        dup_kept = sum(r["kept"] for g in dups for r in g[1:])
        print("\n" + "=" * 90)
        print("DUPLICATE-SST GRANULES (identical SST under both -D- and -N-; pipeline counts BOTH)")
        print("=" * 90)
        for g in dups:
            print(f"  {g[0]['sensor']}  provided={g[0]['provided']:,} kept={g[0]['kept']:,}  "
                  f"appears as: " + ", ".join(sorted(set(r['dn'] for r in g))))
            for r in g:
                print(f"      {r['name']}")
        print(f"\n  Double-counted by pipeline: provided +{dup_prov:,}  kept +{dup_kept:,}")
        print(f"  Deduplicated unique totals: provided={prov_all-dup_prov:,}  "
              f"kept={kept_all-dup_kept:,}")

    print("\n  Quality-level histogram over provided pixels (0=worst .. 5=best):")
    tot = qhist_total.sum()
    for q in range(6):
        c = int(qhist_total[q])
        pct = (100.0 * c / tot) if tot else 0.0
        flag = "  <- kept (>=5)" if q >= 5 else ""
        print(f"    q={q}: {c:>14,} ({pct:5.1f}%){flag}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download", help="fetch the extra granules from Earthdata")
    sub.add_parser("analyze", help="analyze downloaded granules + write plot")
    sub.add_parser("list", help="just list the extra granule set")
    args = ap.parse_args()

    if args.cmd == "download":
        cmd_download(args)
    elif args.cmd == "analyze":
        cmd_analyze(args)
    elif args.cmd == "list":
        for sensor, by_doy in extra_granules().items():
            for doy, lst in by_doy.items():
                print(f"{sensor} DOY {doy}: {len(lst)}")
                for n in lst:
                    print(f"  {n}")


if __name__ == "__main__":
    main()
