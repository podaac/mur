#!/usr/bin/env python3
"""Difference images between MUR L4 granules: one pair, or a daily animation.

    # How each day changed from the day before, over the last two weeks (GIF)
    python utils/l4_delta_anim.py

    # ...from three days before, at 1 km thinned 10x, sea ice instead of SST
    python utils/l4_delta_anim.py --lag 3 --resolution 1km --stride 10 \\
        --field sea_ice_fraction

    # What reanalysis changed relative to the NRT of the same day
    python utils/l4_delta_anim.py --lag 0 --mode rea --base-mode nrt

    # Any two granules, local or s3:// (e.g. MAAP against ops), as one PNG
    python utils/l4_delta_anim.py --pair maap.nc ops.nc --labels MAAP ops

WHERE GRANULES COME FROM
    The promoted copies run_mur_maap.py keeps at
    <root>/mur/l4/<resolution>/<year>/<YYYYMMDD>09-...-<mode>.nc (see
    mur_maap.paths.l4_key). --root is the pipeline's maap.workspace_root by
    default. It may also be a local directory with the same layout, such as
    the workspace mount inside a MAAP ADE (/projects/my-private-bucket),
    which reads 1 km granules in place instead of downloading ~750 MB each.
    s3:// granules are downloaded once into --cache.

WHAT A FRAME SHOWS
    field(D) - field(D - lag), one pixel per grid cell after --stride (25 km
    stays at full resolution by default), on a fixed symmetric colour scale so
    frames compare. Each frame's title names the two granules' modes, since
    "best" can pair a reanalysis with an NRT. Missing granules are skipped
    with a warning rather than failing the run.
"""
import argparse
import dataclasses
import datetime
import json
import pathlib
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mur_maap import paths  # noqa: E402

MODES = ("best", "rea", "nrt")
# Per-field default half-range of the colour scale, in the field's own units.
DEFAULT_VMAX = {"analysed_sst": 1.0, "sst_anomaly": 1.0,
                "analysis_error": 0.2, "sea_ice_fraction": 0.3}
NO_DATA_RGB = (0.55, 0.55, 0.55)


# -- selecting granules ------------------------------------------------------

def mode_order(mode: str) -> Tuple[str, ...]:
    """Modes to try for a day, most preferred first. "best" means the
    reanalysis if one exists yet, else the NRT."""
    return ("rea", "nrt") if mode == "best" else (mode,)


def frame_days(end: datetime.date, days: int) -> List[datetime.date]:
    return [end - datetime.timedelta(days=i) for i in range(days - 1, -1, -1)]


@dataclasses.dataclass
class Granule:
    day: datetime.date
    mode: str
    href: str


class Store:
    """Finds and opens granules under a root, either s3:// or a directory."""

    def __init__(self, root: str, cache: pathlib.Path):
        self.root = root.rstrip("/")
        self.cache = cache
        self._ws = None
        # Sizes seen by exists(), so a cached copy of a granule that a later
        # run rewrote (NRT days are redone until their reanalysis) is
        # downloaded again rather than reused.
        self._sizes: Dict[str, int] = {}

    def _bucket(self):
        if self._ws is None:
            from maap.maap import MAAP
            from mur_maap.workspace import WorkspaceBucket
            self._ws = WorkspaceBucket(MAAP())
        return self._ws

    def exists(self, href: str) -> bool:
        if not href.startswith("s3://"):
            return pathlib.Path(href).is_file()
        bucket, key = paths.split_href(href)
        try:
            head = self._bucket().s3().head_object(Bucket=bucket, Key=key)
        except Exception:
            return False
        self._sizes[href] = head["ContentLength"]
        return True

    def find(self, day: datetime.date, mode: str,
             resolution: str) -> Optional[Granule]:
        for m in mode_order(mode):
            href = paths.href(self.root, paths.l4_key(day, m, resolution))
            if self.exists(href):
                return Granule(day, m, href)
        return None

    def local(self, href: str) -> pathlib.Path:
        """A local path for href, downloading an s3:// object once."""
        if not href.startswith("s3://"):
            return pathlib.Path(href)
        bucket, key = paths.split_href(href)
        dest = self.cache / key
        size = self._sizes.get(href)
        if not dest.is_file() or (size is not None and dest.stat().st_size != size):
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"  downloading {href}")
            part = dest.with_suffix(dest.suffix + ".part")
            self._bucket().s3().download_file(bucket, key, str(part))
            part.rename(dest)
        return dest


# -- reading and differencing ------------------------------------------------

def read_field(path: pathlib.Path, field: str, stride: int) -> np.ma.MaskedArray:
    """One 2-D field, scaled and masked, thinned by stride, south row first."""
    import netCDF4
    with netCDF4.Dataset(path) as ds:
        v = ds[field]
        v.set_auto_maskandscale(True)
        a = v[0, ::stride, ::stride] if v.ndim == 3 else v[::stride, ::stride]
        units = getattr(v, "units", "")
    a = np.ma.masked_invalid(np.ma.asarray(a, dtype=np.float64))
    a.units = units
    return a


def difference(a: np.ma.MaskedArray, b: np.ma.MaskedArray) -> np.ma.MaskedArray:
    if a.shape != b.shape:
        raise ValueError(f"grids differ: {a.shape} vs {b.shape}")
    return np.ma.masked_array(a.filled(np.nan) - b.filled(np.nan),
                              mask=np.ma.getmaskarray(a) | np.ma.getmaskarray(b))


def stats(d: np.ma.MaskedArray, big: float) -> Dict[str, float]:
    v = d.compressed()
    if v.size == 0:
        return {"n": 0, "mean": float("nan"), "rms": float("nan"),
                "p99": float("nan"), "max": float("nan"), "frac_big": float("nan")}
    av = np.abs(v)
    return {"n": int(v.size), "mean": float(v.mean()),
            "rms": float(np.sqrt((v * v).mean())),
            "p99": float(np.percentile(av, 99)), "max": float(av.max()),
            "frac_big": float((av >= big).mean())}


def stats_line(s: Dict[str, float], units: str, big: float) -> str:
    if not s["n"]:
        return "no cells valid in both"
    u = f" {units}" if units else ""
    return (f"mean {s['mean']:+.3f}{u}   rms {s['rms']:.3f}   "
            f"p99 |d| {s['p99']:.3f}   max |d| {s['max']:.2f}   "
            f"|d| >= {big:g}: {100 * s['frac_big']:.2f}%   "
            f"cells {s['n']:,}")


# -- rendering ---------------------------------------------------------------

def render(d: np.ma.MaskedArray, title: str, subtitle: str, vmax: float,
           units: str, cmap: str = "RdBu_r"):
    """A PIL image with one pixel per grid cell, plus a title and colour bar."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib import colormaps
    from PIL import Image

    ny, nx = d.shape
    dpi = 100
    top, bottom = 56, 64
    W, H = nx, ny + top + bottom
    fig = Figure(figsize=(W / dpi, H / dpi), dpi=dpi, facecolor="white")
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0, bottom / H, 1, ny / H])
    cm = colormaps[cmap].copy()
    cm.set_bad(NO_DATA_RGB)
    im = ax.imshow(d, origin="lower", cmap=cm, vmin=-vmax, vmax=vmax,
                   interpolation="nearest", aspect="auto")
    ax.set_axis_off()
    fs = max(8, min(14, nx // 110))
    fig.text(0.01, 1 - 8 / H, title, va="top", fontsize=fs + 2, weight="bold")
    fig.text(0.01, 1 - 34 / H, subtitle, va="top", fontsize=fs)
    cax = fig.add_axes([0.25, 34 / H, 0.5, 14 / H])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal", extend="both")
    cb.ax.tick_params(labelsize=fs - 1)
    fig.text(0.76, 41 / H, units, va="center", fontsize=fs - 1)
    fig.canvas.draw()
    return Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[..., :3])


def save_gif(frames, out: pathlib.Path, fps: float) -> None:
    """One shared palette, so colours do not shift from frame to frame."""
    from PIL import Image
    base = frames[0].quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    q = [base] + [f.quantize(palette=base, dither=Image.Dither.NONE)
                  for f in frames[1:]]
    q[0].save(out, save_all=True, append_images=q[1:],
              duration=int(1000 / fps), loop=0, optimize=False)


# -- entry points ------------------------------------------------------------

def default_root(config_path: pathlib.Path) -> Optional[str]:
    if config_path.is_file():
        root = json.loads(config_path.read_text()).get("maap", {}).get("workspace_root")
        if root and "<" not in root:
            return root
    return None


def run_pair(args, store: Store) -> int:
    a_href, b_href = args.pair
    la, lb = args.labels or (pathlib.Path(a_href).name, pathlib.Path(b_href).name)
    a = read_field(store.local(a_href), args.field, args.stride)
    b = read_field(store.local(b_href), args.field, args.stride)
    d = difference(a, b)
    vmax = args.vmax or DEFAULT_VMAX.get(args.field, 1.0)
    s = stats(d, args.big)
    line = stats_line(s, a.units, args.big)
    print(f"{la} - {lb}: {line}")
    out = pathlib.Path(args.out or "l4_pair_diff.png")
    render(d, f"{args.field}: {la} - {lb}", line, vmax, a.units).save(out)
    print(f"wrote {out}")
    return 0


def run_series(args, store: Store) -> int:
    end = (datetime.date.fromisoformat(args.end) if args.end
           else datetime.date.today() - datetime.timedelta(days=1))
    base_mode = args.base_mode or args.mode
    if args.lag == 0 and base_mode == args.mode:
        print("ERROR: --lag 0 compares a day with itself; give --base-mode too",
              file=sys.stderr)
        return 2
    vmax = args.vmax or DEFAULT_VMAX.get(args.field, 1.0)
    frames, summary = [], []
    frames_dir = pathlib.Path(args.frames_dir) if args.frames_dir else None
    if frames_dir:
        frames_dir.mkdir(parents=True, exist_ok=True)

    for day in frame_days(end, args.days):
        prior = day - datetime.timedelta(days=args.lag)
        ga = store.find(day, args.mode, args.resolution)
        gb = store.find(prior, base_mode, args.resolution)
        if not ga or not gb:
            missing = [str(x) for x, g in ((day, ga), (prior, gb)) if not g]
            print(f"  {day}: skipped, no granule for {', '.join(missing)}")
            continue
        a = read_field(store.local(ga.href), args.field, args.stride)
        b = read_field(store.local(gb.href), args.field, args.stride)
        d = difference(a, b)
        s = stats(d, args.big)
        line = stats_line(s, a.units, args.big)
        title = (f"{args.field} {args.resolution}: {day} {ga.mode} - "
                 f"{prior} {gb.mode}")
        print(f"  {day}: {line}")
        img = render(d, title, line, vmax, a.units)
        if frames_dir:
            img.save(frames_dir / f"{day:%Y%m%d}.png")
        frames.append(img)
        summary.append({"day": str(day), "mode": ga.mode, "base_day": str(prior),
                        "base_mode": gb.mode, **s})

    if not frames:
        print("ERROR: no frames; nothing found under " + store.root, file=sys.stderr)
        return 1
    out = pathlib.Path(args.out or
                       f"l4_delta_{args.resolution}_{args.field}_lag{args.lag}_{end:%Y%m%d}.gif")
    save_gif(frames, out, args.fps)
    out.with_suffix(".json").write_text(json.dumps(summary, indent=1))
    print(f"wrote {out} ({len(frames)} frames) and {out.with_suffix('.json').name}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="where mur/l4/ lives: s3://bucket/prefix or a "
                    "local directory. Default: the config's maap.workspace_root, "
                    "else this account's MAAP workspace")
    ap.add_argument("--config", default=str(REPO / "config.maap.json"))
    ap.add_argument("--resolution", default="25km", choices=("25km", "1km"))
    ap.add_argument("--field", default="analysed_sst",
                    help="analysed_sst, sst_anomaly, analysis_error, "
                         "sea_ice_fraction, ...")
    ap.add_argument("--end", help="last day shown, YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--days", type=int, default=14, help="frames (default 14)")
    ap.add_argument("--lag", type=int, default=1,
                    help="compare each day with the one this many days before "
                         "(default 1; 0 with --base-mode compares modes)")
    ap.add_argument("--mode", default="best", choices=MODES,
                    help="granule for each day: best (rea, else nrt), rea, nrt")
    ap.add_argument("--base-mode", choices=MODES,
                    help="granule for the earlier day (default: same as --mode)")
    ap.add_argument("--stride", type=int,
                    help="keep every Nth cell (default 1 for 25km, 10 for 1km)")
    ap.add_argument("--vmax", type=float, help="colour scale half-range")
    ap.add_argument("--big", type=float, default=0.5,
                    help="threshold for the |d| >= share in the stats line")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--out", help="output .gif (series) or .png (--pair)")
    ap.add_argument("--frames-dir", help="also write each frame as a PNG here")
    ap.add_argument("--cache", default=str(pathlib.Path.home() / ".cache" / "mur-l4"),
                    help="where s3:// granules are downloaded")
    ap.add_argument("--pair", nargs=2, metavar=("A", "B"),
                    help="difference just these two granules (A - B) as one PNG")
    ap.add_argument("--labels", nargs=2, metavar=("A", "B"))
    args = ap.parse_args(argv)
    if args.stride is None:
        args.stride = 10 if args.resolution == "1km" else 1

    root = args.root or default_root(pathlib.Path(args.config))
    store = Store(root or "", pathlib.Path(args.cache))
    if args.pair:
        return run_pair(args, store)
    if not root:
        from maap.maap import MAAP
        from mur_maap.workspace import WorkspaceBucket
        store = Store(WorkspaceBucket(MAAP()).path().uri, pathlib.Path(args.cache))
    print(f"granules from {store.root}/mur/l4/{args.resolution}/")
    return run_series(args, store)


if __name__ == "__main__":
    sys.exit(main())
