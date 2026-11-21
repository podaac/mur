#!/usr/bin/env python3
"""Replay a staged prod run on MAAP and compare the result with prod.

The case comes from utils/stage_prod_snapshot.py. Both variants run the
registered MAAP containers through run_mur_maap.py --frozen-case (see
mur_maap/frozen.py for what each variant does):

  python utils/regress_mur_maap.py run --config config.maap.json \\
      --case s3://nasa-maap-mur-sst/regression/20261024/case.json --variant both
  python utils/regress_mur_maap.py compare --config config.maap.json \\
      --case s3://nasa-maap-mur-sst/regression/20261024/case.json --out regress_20261024

`run` starts one run_mur_maap.py per variant. Each covers prod's REA day plus
its three NRT days, oldest first, the order prod ran them in. The variants
write to separate roots, so `both` runs them side by side.

`compare` writes report.json and report.html. For every variant and day it
compares:
  * MRVA's inputs log (which BIC and buoy days were read, and the point count
    of each) with prod's _inputs.txt;
  * coefficient files c06..c11 and u06..u08: identical bytes or not;
  * the 1 km and 0.25 deg L4 fields: difference statistics;
  * chained only: each BIC MAAP rebuilt, and its L2Plist, against prod's.
    This is the L2P stage check.

Differences that a prod quirk explains are labelled "expected", not counted
as failures. These are dt_1km_data and the MUR25 ice, which prod takes from
caches written once per day; see the KNOWN dict below.
"""
import argparse
import concurrent.futures
import datetime
import gzip
import hashlib
import json
import pathlib
import subprocess
import sys
from typing import Dict, List, Optional

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "utils"))

from mur_maap import frozen as fz  # noqa: E402
from mur_maap import paths  # noqa: E402

L4_FIELDS = {
    "analysed_sst": 0.01,       # K: |d| at or above this counts as "big"
    "analysis_error": 0.01,
    "sea_ice_fraction": 0.01,
    "mask": 0.5,
    "sst_anomaly": 0.01,
    "dt_1km_data": 0.5,
}
# Prod differences we know the cause of. Each is keyed by field and
# resolution.
KNOWN = {
    ("dt_1km_data", "1km"): "prod reads hiresdt_<day>.grd, which is written once and "
                            "never refreshed (makehiresgrid.m:15)",
    ("sea_ice_fraction", "25km"): "prod's MUR25 ice map cache is written once per day "
                                  "(makeMUR25ice.m:3-43)",
}


# --- S3 --------------------------------------------------------------------

class Store:
    def __init__(self):
        from mur_maap import auth
        from mur_maap.client import MaapPyClient
        from mur_maap.version import ALGORITHM_VERSION
        if not auth.load():
            raise SystemExit("No MAAP token: set MAAP_PGT or write ~/.maap-token")
        self.s3 = MaapPyClient(queue="__read_only__",
                               version=ALGORITHM_VERSION).workspace.s3()

    @staticmethod
    def split(uri):
        bucket, _, key = uri[len("s3://"):].partition("/")
        return bucket, key

    def text(self, uri) -> Optional[str]:
        b, k = self.split(uri)
        try:
            return self.s3.get_object(Bucket=b, Key=k)["Body"].read().decode("utf-8", "replace")
        except Exception:                                  # noqa: BLE001
            return None

    def list(self, prefix) -> List[str]:
        b, k = self.split(prefix)
        out = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=k):
            out += [f"s3://{b}/{o['Key']}" for o in page.get("Contents", [])]
        return out

    def fetch(self, uri, cache: pathlib.Path) -> Optional[pathlib.Path]:
        b, k = self.split(uri)
        dest = cache / b / k
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.s3.download_file(b, k, str(dest))
        except Exception:                                  # noqa: BLE001
            return None
        return dest


def read_case(href: str, store: Optional[Store]) -> Dict:
    if href.startswith("s3://"):
        text = store.text(href)
        if text is None:
            raise SystemExit(f"cannot read {href}")
        return json.loads(text)
    return json.loads(pathlib.Path(href).read_text())


# --- run --------------------------------------------------------------------

def offsets_spec(case: Dict) -> str:
    run_date = datetime.date.fromisoformat(case["run_date"])
    offs = sorted((datetime.date.fromisoformat(v["date"]) - run_date).days
                  for v in case["days"].values())
    if offs != list(range(offs[0], offs[-1] + 1)):
        raise SystemExit(f"case days are not contiguous: {offs}")
    return f"-p={offs[0]}:{offs[-1]}" if len(offs) > 1 else f"-p={offs[0]}"


def run_command(args, case: Dict, variant: str) -> List[str]:
    cmd = [sys.executable, str(REPO / "run_mur_maap.py"), "--config", args.config,
           "--date", case["run_date"], offsets_spec(case),
           "--frozen-case", args.case, "--frozen-variant", variant]
    if args.queue:
        cmd += ["--queue", args.queue]
    if args.debug:
        cmd.append("--debug")
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def cmd_run(args):
    store = Store() if args.case.startswith("s3://") and not args.dry_run else None
    case = read_case(args.case, store) if store or not args.case.startswith("s3://") else None
    if case is None:
        raise SystemExit("--dry-run with an s3:// case needs a local copy of case.json")
    variants = list(fz.VARIANTS) if args.variant == "both" else [args.variant]
    logs = pathlib.Path(args.log_dir or f"regress_{case['run_date'].replace('-', '')}")
    logs.mkdir(parents=True, exist_ok=True)
    procs = {}
    for v in variants:
        cmd = run_command(args, case, v)
        print(f"[{v}] $ {' '.join(cmd)}", flush=True)
        log = open(logs / f"run_{v}.log", "w")
        procs[v] = (subprocess.Popen(cmd, cwd=str(REPO), stdout=log,
                                     stderr=subprocess.STDOUT), log)
        print(f"[{v}] log: {logs / f'run_{v}.log'}")
    rc = 0
    for v, (p, log) in procs.items():
        code = p.wait()
        log.close()
        print(f"[{v}] exit {code}")
        rc = rc or code
    return rc


# --- compare ----------------------------------------------------------------

def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def content_md5(path: Optional[pathlib.Path]) -> Optional[str]:
    """md5 of the decompressed bytes, so .bic and .bic.gz compare equal."""
    if path is None:
        return None
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return md5_bytes(data)


def compare_inputs(prod_text: Optional[str], maap_text: Optional[str]) -> Dict:
    from compare_maap_prod_inputs import parse_inputs_txt
    if prod_text is None or maap_text is None:
        side = "prod" if prod_text is None else "maap"
        return {"ok": None, "why": f"{side} inputs log missing"}
    prt, prows = parse_inputs_txt(prod_text)
    mrt, mrows = parse_inputs_txt(maap_text)
    rows = []
    for key in sorted(set(prows) | set(mrows)):
        p, m = prows.get(key), mrows.get(key)
        rows.append({"sensor": key[0], "day": f"{key[1]}_{key[2]:03d}",
                     "prod": p[0] if p else None, "maap": m[0] if m else None})
    ok = prt == mrt and all(r["prod"] == r["maap"] for r in rows)
    return {"ok": ok, "realtime": [prt, mrt], "rows": rows}


def compare_l4(prod: Optional[pathlib.Path], maap: Optional[pathlib.Path],
               resolution: str, stride: int) -> Dict:
    if prod is None or maap is None:
        return {"ok": None, "why": ("prod" if prod is None else "maap") + " granule missing"}
    from l4_delta_anim import difference, read_field, stats
    fields = {}
    for field, big in L4_FIELDS.items():
        try:
            a, b = read_field(maap, field, stride), read_field(prod, field, stride)
        except (KeyError, IndexError):
            continue
        try:
            s = stats(difference(a, b), big)
        except ValueError as exc:
            fields[field] = {"error": str(exc)}
            continue
        s["identical"] = bool(s["n"] and s["max"] == 0)
        s["expected"] = KNOWN.get((field, resolution))
        fields[field] = s
    unexplained = [f for f, s in fields.items()
                   if not s.get("identical") and not s.get("expected")]
    return {"ok": not unexplained, "fields": fields, "differ": unexplained}


def compare_day(store: Store, case: Dict, variant: str, day_tag: str,
                cache: pathlib.Path, stride: int) -> Dict:
    root = case["roots"][variant]
    info = case["days"][day_tag]
    d = datetime.date.fromisoformat(info["date"])
    mode = info["mode"]
    prod = case["prod"].get(day_tag, {})
    replay = f"{root}/{paths.MUR_ROOT}/replay/{day_tag}"
    listed = store.list(replay + "/")
    out = {"day": day_tag, "date": info["date"], "mode": mode}

    maap_inputs = next((u for u in listed if u.endswith("_inputs.txt")), None)
    out["inputs"] = compare_inputs(store.text(prod["inputs_txt"]) if prod.get("inputs_txt") else None,
                                   store.text(maap_inputs) if maap_inputs else None)

    coeffs = {}
    maap_by_ext = {u.rsplit(".", 1)[-1]: u for u in listed
                   if not u.endswith((".txt", ".json"))}
    for ext in sorted(set(prod.get("csp", {})) | set(maap_by_ext)):
        p = store.fetch(prod["csp"][ext], cache) if ext in prod.get("csp", {}) else None
        m = store.fetch(maap_by_ext[ext], cache) if ext in maap_by_ext else None
        coeffs[ext] = {"prod": p is not None, "maap": m is not None,
                       "identical": (content_md5(p) == content_md5(m)) if p and m else None}
    out["coefficients"] = coeffs

    l4 = {}
    for res in ("1km", "25km"):
        p_href = prod.get("l4", {}).get(res)
        p = store.fetch(p_href, cache) if p_href else None
        m = store.fetch(paths.l4_href(root, d, mode, res), cache)
        # The 0.25 deg grid is small; read all of it.
        l4[res] = compare_l4(p, m, res, stride if res == "1km" else 1)
    out["l4"] = l4
    return out


def compare_bics(store: Store, case: Dict, cache: pathlib.Path) -> List[Dict]:
    """Chained only: each BIC MAAP rebuilt from prod's granules, against
    prod's BIC and L2Plist. The prod copies come from the earliest snapshot
    day that captured them, the version prod's first reader saw."""
    from compare_maap_prod_inputs import diff_names, file_names
    root = case["roots"]["chained"]
    snap = case["source"]["snapshot"]
    rows = []
    rebuilt = [u for u in store.list(f"{root}/{paths.MUR_ROOT}/replay/l2p/")
               if u.rsplit("/", 1)[-1].startswith("L2Plist_")]
    first_day = sorted(case["days"])[0]
    for l2p_href in sorted(rebuilt):
        name = l2p_href.rsplit("/", 1)[-1]
        sensor, year, doy = name[:-4].split("_")[2:5]
        data_day = datetime.date(int(year), 1, 1) + datetime.timedelta(days=int(doy) - 1)
        prod_list = None
        prod_bic = None
        for t in sorted(case["days"]):
            base = f"{snap}/days/{t}/bic/{sensor}/{year}"
            prod_list = prod_list or store.text(f"{base}/{name}")
            prod_bic = prod_bic or store.fetch(
                f"{base}/Global_{sensor}_{year}_{doy}.bic.gz", cache)
        maap_bic = next((store.fetch(h, cache) for h in
                         paths.bic_candidate_hrefs(root, sensor, data_day)
                         if store.fetch(h, cache)), None)
        names = diff_names(file_names(prod_list or ""), file_names(store.text(l2p_href) or ""))
        rows.append({"sensor": sensor, "day": f"{year}_{doy}",
                     "granules": names,
                     "bic_identical": (content_md5(prod_bic) == content_md5(maap_bic))
                     if prod_bic and maap_bic else None,
                     "first_snapshot_day": first_day})
    return rows


def render_html(report: Dict) -> str:
    from compare_maap_prod_inputs import _e, _pill
    css = """
:root{--bg:#fff;--fg:#1d1d1f;--mut:#6b6b70;--line:#e3e3e6;--ok:#1b7f3b;--bad:#b3261e;--na:#8a8a8f;--exp:#8a5a00}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececef;--mut:#9a9aa0;--line:#2c2c31;--ok:#5cc27e;--bad:#ff7b72;--na:#8a8a8f;--exp:#e0b050}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:24px auto;max-width:1100px;padding:0 16px}
h1{font-size:20px}h2{font-size:16px;margin-top:28px}h3{font-size:14px;margin:16px 0 4px}
table{border-collapse:collapse;width:100%;margin:6px 0 12px}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;font-variant-numeric:tabular-nums}
th{color:var(--mut);font-weight:500}.pill{border-radius:9px;padding:1px 8px;font-size:12px}
.ok{color:var(--ok)}.bad{color:var(--bad)}.na{color:var(--na)}.exp{color:var(--exp)}.mut{color:var(--mut)}
"""
    h = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>MUR regression {_e(report['run_date'])}</title><style>{css}</style>",
         f"<h1>MUR regression: prod run {_e(report['run_date'])}</h1>",
         f"<p class=mut>case {_e(report['case'])} &middot; compared {_e(report['compared_at'])}"
         f" &middot; exact capture: {_e(report['exact'])}</p>"]
    if report.get("notes"):
        h.append("<h2>Capture notes</h2><ul>" + "".join(
            f"<li>{_e(json.dumps(n))}</li>" for n in report["notes"]) + "</ul>")
    for variant, days in report["variants"].items():
        h.append(f"<h2>{_e(variant)}</h2>")
        for d in days:
            h.append(f"<h3>{_e(d['date'])} ({_e(d['mode'])}) &nbsp;"
                     f"inputs {_pill(d['inputs'].get('ok'))} &nbsp;"
                     f"L4 1km {_pill(d['l4']['1km'].get('ok'))} &nbsp;"
                     f"L4 25km {_pill(d['l4']['25km'].get('ok'))}</h3>")
            rows = [r for r in d["inputs"].get("rows", []) if r["prod"] != r["maap"]]
            if rows:
                h.append("<table><tr><th>input</th><th>day</th><th>prod points</th><th>maap points</th></tr>"
                         + "".join(f"<tr><td>{_e(r['sensor'])}</td><td>{_e(r['day'])}</td>"
                                   f"<td>{_e(r['prod'])}</td><td>{_e(r['maap'])}</td></tr>" for r in rows)
                         + "</table>")
            for res in ("1km", "25km"):
                f = d["l4"][res].get("fields")
                if not f:
                    if d["l4"][res].get("why"):
                        h.append(f"<p class=na>L4 {res}: {_e(d['l4'][res]['why'])}</p>")
                    continue
                h.append(f"<table><tr><th>L4 {res}</th><th>rms</th><th>p99 |d|</th><th>max |d|</th>"
                         f"<th>cells</th><th></th></tr>")
                for name, s in f.items():
                    if "error" in s:
                        h.append(f"<tr><td>{_e(name)}</td><td colspan=5 class=bad>{_e(s['error'])}</td></tr>")
                        continue
                    tag = ("<span class=ok>identical</span>" if s["identical"] else
                           f"<span class=exp title='{_e(s['expected'])}'>expected</span>" if s["expected"]
                           else "<span class=bad>differs</span>")
                    h.append(f"<tr><td>{_e(name)}</td><td>{s['rms']:.4g}</td><td>{s['p99']:.4g}</td>"
                             f"<td>{s['max']:.4g}</td><td>{s['n']:,}</td><td>{tag}</td></tr>")
                h.append("</table>")
            co = d["coefficients"]
            if co:
                h.append("<p>coefficients: " + " ".join(
                    f"{_e(k)} {_pill(v['identical'], na='only ' + ('prod' if v['prod'] else 'maap'))}"
                    for k, v in co.items()) + "</p>")
    if report.get("bics"):
        h.append("<h2>L2P stage (chained: rebuilt BICs against prod's)</h2><table>"
                 "<tr><th>sensor</th><th>day</th><th>granules prod / maap / common</th><th>BIC</th></tr>")
        for r in report["bics"]:
            g = r["granules"]
            h.append(f"<tr><td>{_e(r['sensor'])}</td><td>{_e(r['day'])}</td>"
                     f"<td>{g['prod']} / {g['maap']} / {g['common']}</td>"
                     f"<td>{_pill(r['bic_identical'], 'identical')}</td></tr>")
        h.append("</table>")
    return "\n".join(h)


def cmd_compare(args):
    store = Store()
    case = read_case(args.case, store)
    out = pathlib.Path(args.out or f"regress_{case['run_date'].replace('-', '')}")
    cache = out / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    variants = list(fz.VARIANTS) if args.variant == "both" else [args.variant]
    report = {"case": args.case, "run_date": case["run_date"], "exact": case.get("exact"),
              "compared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
              "notes": case.get("notes", []), "variants": {}}
    jobs = [(v, t) for v in variants for t in sorted(case["days"])]
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda vt: compare_day(store, case, vt[0], vt[1], cache,
                                                     args.stride), jobs))
    for (v, _t), r in zip(jobs, results):
        report["variants"].setdefault(v, []).append(r)
    if "chained" in variants:
        report["bics"] = compare_bics(store, case, cache)
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str))
    (out / "report.html").write_text(render_html(report))
    print(f"wrote {out / 'report.json'} and {out / 'report.html'}")
    bad = [(v, r["day"]) for v in report["variants"] for r in report["variants"][v]
           if r["inputs"].get("ok") is False or r["l4"]["1km"].get("ok") is False]
    for v, t in bad:
        print(f"  {v} {t}: differs from prod")
    return 1 if bad else 0


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="replay the case on MAAP")
    r.add_argument("--config", required=True)
    r.add_argument("--case", required=True, help="case.json href or path")
    r.add_argument("--variant", choices=(*fz.VARIANTS, "both"), default="both")
    r.add_argument("--queue")
    r.add_argument("--log-dir")
    r.add_argument("--debug", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_run)
    c = sub.add_parser("compare", help="compare a replay with prod")
    c.add_argument("--config", help="unused; accepted for symmetry with run")
    c.add_argument("--case", required=True)
    c.add_argument("--variant", choices=(*fz.VARIANTS, "both"), default="both")
    c.add_argument("--out", help="report directory (default regress_<YYYYMMDD>)")
    c.add_argument("--stride", type=int, default=4,
                   help="read every Nth cell of the 1 km grid (default: %(default)s; 1 = all)")
    c.set_defaults(func=cmd_compare)
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
