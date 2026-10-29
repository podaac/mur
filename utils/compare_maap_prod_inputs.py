#!/usr/bin/env python3
"""Compare what went INTO one analysis day on MAAP against production.

    python utils/compare_maap_prod_inputs.py --date 2026-10-20 --host podaac-mure
    python utils/compare_maap_prod_inputs.py --year 2026 --doy 293 \\
        --host jleach@podaac-ops-measures --ssh-opt -p --ssh-opt 2222
    python utils/compare_maap_prod_inputs.py --date 2026-10-20 --skip-remote

WHY THIS EXISTS
    MAAP L4 granules do not quite match production, and the first thing to
    rule out is the inputs. Both pipelines already write a record of their
    inputs at every stage -- the same MATLAB writes them on both sides -- so
    this fetches those records and diffs them stage by stage. It reads logs
    and listings only; no BIC, L2P or coefficient data is downloaded.

WHAT IS COMPARED, PER STAGE
    MRVA ingest   <YYYYMMDD>09_MRVA4_Global_inputs.txt, written by makebiq.m:
                  one "SENSOR YYYY DDD N points" line per BIC/IQUAM0 file the
                  analysis actually read, plus a "RealTime" line on NRT runs.
                  This is the decisive one -- what MRVA saw, not what it was
                  handed. prod: <csp-root>/<year>/;  MAAP: the mrva DPS job.
    MRVA params   (MAAP only) the job's own inputs from _job.json -- above all
                  whether prior_csp_file was passed. Without it MRVA
                  bootstraps instead of chaining from yesterday, and no input
                  comparison will explain the difference.
    L2P -> BIC    L2Plist_Global_<SENSOR>_<YYYY>_<DDD>.txt, written by
                  l2p2bic.m: the granules folded into each BIC, for every
                  sensor across the +/- dayrange window.
    Land/ice      icefiles_<YYYY>_<DDD>.txt: the OSI-SAF files used.
    iQUAM         .bii sizes over +/- the buoy dayrange (it has no list file).

    Raw files from both sides are saved under --out for inspection, together
    with the chosen MRVA job's stdout/stderr and the canonical MAAP manifests.
    report.json holds every difference; report.html is the same, readable,
    and self-contained (no external assets), so it can be mailed or attached.

WHICH MAAP RUN
    A day is analysed more than once on MAAP: NRT, then REA, and L2P rewrites
    a BIC as late granules land. Jobs are found by listing each stage's
    dps_output tree, whose path carries the run time -- list_jobs does not
    return a job's inputs, so it cannot say which day a job was for.

      MRVA    --mode auto (default) picks the latest MAAP run of the same kind
              as prod's file (prod's REA overwrites its NRT inputs.txt); nrt
              or rea forces one. Every candidate is listed.
      L2P     the LATEST L2Plist is compared against prod's (both sides keep
              only their final version). When the version MRVA actually read
              -- the last one written before the MRVA job started -- differs,
              that is reported too.

REMOTE ACCESS
    One `ssh <host> bash -s` reads every file, so a password-authenticated
    host prompts once rather than once per file, and a missing file is
    reported rather than aborting the batch. The remote roots default to the
    production layout (see collect_prod_inputs.py); override them with the
    --*-root flags for a mirror such as podaac-mure.
"""
import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import shlex
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "utils"))

import collect_prod_inputs as prod  # noqa: E402  -- prod paths + sensor table

# Parameters worth showing from an MRVA job's own inputs.
MRVA_PARAMS = ("mode", "prior_csp_file", "max_level", "sensors",
               "sensor_inputs_manifest", "seasonal_file", "polar_cap_edge_file",
               "landice_ice_p011_file", "landice_grid_p01_file",
               "landice_icefiles_p011_file", "mur25_grid_file")

# dps_output/<algo>/<version>/[<tag>/]YYYY/MM/DD/HH/MM/SS/<n>/<file>
DPS_KEY = re.compile(
    r"^(?P<job>(?:.*/)?dps_output/(?P<algo>[^/]+)/[^/]+/(?:.+?/)?"
    r"(?P<ts>\d{4}/\d\d/\d\d/\d\d/\d\d/\d\d/\d+))/(?P<rel>.+)$")

INPUTS_LINE = re.compile(r"^\s*(\S+)\s+(\d{4})\s+(\d{1,3})\s+(\d+)\s+points?\b(.*)$")


@dataclasses.dataclass(frozen=True)
class DpsFile:
    key: str
    job: str            # the job's directory, i.e. the key prefix
    algo: str           # e.g. mur-l2p_1756
    ts: Tuple[int, ...] # run time from the path, sortable
    rel: str            # path inside the job directory

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def when(self) -> str:
        y, mo, d, h, mi, s = self.ts[:6]
        return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}Z"


def parse_dps_key(key: str) -> Optional[DpsFile]:
    m = DPS_KEY.match(key)
    if not m:
        return None
    ts = tuple(int(p) for p in m["ts"].split("/"))
    return DpsFile(key=key, job=m["job"], algo=m["algo"], ts=ts, rel=m["rel"])


def parse_inputs_txt(text: str) -> Tuple[bool, Dict[Tuple[str, int, int], Tuple[int, str]]]:
    """(realtime, {(sensor, year, doy): (points, note)}) from a makebiq log."""
    realtime = False
    rows = {}
    for line in text.splitlines():
        if line.strip().startswith("RealTime"):
            realtime = True
            continue
        m = INPUTS_LINE.match(line)
        if m:
            rows[(m[1], int(m[2]), int(m[3]))] = (int(m[4]), m[5].strip())
    return realtime, rows


def file_names(text: str) -> List[str]:
    """Basenames listed one per line, as l2p2bic.m and the icefiles log write
    them. Basenames because each side records its own directory layout."""
    return [line.strip().rsplit("/", 1)[-1]
            for line in text.splitlines() if line.strip()]


def diff_names(prod_names, maap_names) -> Dict:
    p, m = set(prod_names), set(maap_names)
    return {"prod": len(p), "maap": len(m), "common": len(p & m),
            "only_prod": sorted(p - m), "only_maap": sorted(m - p)}


# --- remote ---------------------------------------------------------------

def remote_script(cat_paths: List[str], size_paths: List[str]) -> str:
    """A bash script that prints each file between markers, or its size."""
    lines = [
        'emit() { if [ -r "$1" ]; then echo "@@@BEGIN $1"; cat "$1"; echo;'
        ' echo "@@@END $1"; else echo "@@@MISSING $1"; fi; }',
        'size() { if [ -e "$1" ]; then echo "@@@SIZE $1'
        ' $(stat -c %s "$1" 2>/dev/null || stat -f %z "$1")";'
        ' else echo "@@@MISSING $1"; fi; }',
    ]
    lines += [f"emit {shlex.quote(p)}" for p in cat_paths]
    lines += [f"size {shlex.quote(p)}" for p in size_paths]
    return "\n".join(lines) + "\n"


def parse_remote_dump(text: str) -> Tuple[Dict[str, Optional[str]], Dict[str, Optional[int]]]:
    contents: Dict[str, Optional[str]] = {}
    sizes: Dict[str, Optional[int]] = {}
    current, buf = None, []
    for line in text.splitlines():
        if current is not None:
            if line == f"@@@END {current}":
                contents[current] = "\n".join(buf).rstrip("\n") + "\n"
                current, buf = None, []
            else:
                buf.append(line)
        elif line.startswith("@@@BEGIN "):
            current = line[len("@@@BEGIN "):]
        elif line.startswith("@@@MISSING "):
            path = line[len("@@@MISSING "):]
            contents.setdefault(path, None)
            sizes.setdefault(path, None)
        elif line.startswith("@@@SIZE "):
            path, _, n = line[len("@@@SIZE "):].rpartition(" ")
            sizes[path] = int(n) if n.isdigit() else None
    return contents, sizes


def fetch_remote(host: str, ssh_opts: List[str], script: str) -> str:
    """Run the script over ssh. stderr is left on the terminal so a password
    prompt (ssh reads it from the tty, not stdin) and any error are seen."""
    cmd = ["ssh", *ssh_opts, host, "bash -s"]
    print(f"Reading production logs: {' '.join(shlex.quote(c) for c in cmd)}")
    done = subprocess.run(cmd, input=script, stdout=subprocess.PIPE, text=True)
    if done.returncode != 0 and "@@@" not in done.stdout:
        raise SystemExit(f"ssh to {host} failed (exit {done.returncode})")
    return done.stdout


# --- MAAP -----------------------------------------------------------------

class Maap:
    """Read-only S3 access to this account's MAAP workspace."""

    def __init__(self):
        from mur_maap import auth
        from mur_maap.client import MaapPyClient
        from mur_maap.version import ALGORITHM_VERSION
        source = auth.load()
        if not source:
            raise SystemExit("No MAAP token: set MAAP_PGT or write ~/.maap-token")
        client = MaapPyClient(queue="__read_only__", version=ALGORITHM_VERSION)
        self.s3 = client.workspace.s3()
        self.ws = client.workspace.path()
        self.bucket = self.ws.bucket
        self._dps_root = None

    def _list(self, prefix: str, delimiter: Optional[str] = None):
        kw = {"Bucket": self.bucket, "Prefix": prefix}
        if delimiter:
            kw["Delimiter"] = delimiter
        for page in self.s3.get_paginator("list_objects_v2").paginate(**kw):
            yield page

    def dps_root(self) -> str:
        """dps_output/ under the workspace prefix, or at the bucket root."""
        if self._dps_root is None:
            for root in (self.ws.key("dps_output") + "/", "dps_output/"):
                if any(p.get("CommonPrefixes") for p in self._list(root, "/")):
                    self._dps_root = root
                    break
            else:
                raise SystemExit(f"no dps_output/ found in s3://{self.bucket}/"
                                 f"{self.ws.prefix}")
        return self._dps_root

    def stage_files(self, stage: str) -> List[DpsFile]:
        """Every file every job of one stage (l2p, mrva, ...) staged out."""
        root = self.dps_root()
        algos = [cp["Prefix"] for page in self._list(root, "/")
                 for cp in page.get("CommonPrefixes", [])
                 if cp["Prefix"][len(root):].startswith(f"mur-{stage}")]
        found = []
        for algo in algos:
            for page in self._list(algo):
                for obj in page.get("Contents", []):
                    f = parse_dps_key(obj["Key"])
                    if f:
                        found.append(f)
        print(f"  {stage}: {len(found)} file(s) across "
              f"{len({f.job for f in found})} job(s) under {', '.join(algos) or '(none)'}")
        return found

    def text(self, key: str) -> Optional[str]:
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None
        return body.decode("utf-8", errors="replace")

    def size(self, key: str) -> Optional[int]:
        try:
            return self.s3.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except Exception:                                  # noqa: BLE001
            return None

    def workspace_key(self, key: str) -> str:
        return self.ws.key(key)


def find_params(node, wanted=MRVA_PARAMS, depth=0) -> Dict:
    """The named parameters wherever they sit in a job's DPS metadata.

    DPS spells them as the CWL does -- prior-csp-file, not prior_csp_file --
    so keys are compared with hyphens folded to underscores. An empty value is
    kept: "prior-csp-file": "" is exactly the finding that matters.
    """
    found = {}
    if depth > 8:
        return found
    if isinstance(node, dict):
        for k, v in node.items():
            name = str(k).replace("-", "_")
            if name in wanted and not isinstance(v, (dict, list)):
                found.setdefault(name, v)
            else:
                for kk, vv in find_params(v, wanted, depth + 1).items():
                    found.setdefault(kk, vv)
    elif isinstance(node, list):
        for v in node:
            for kk, vv in find_params(v, wanted, depth + 1).items():
                found.setdefault(kk, vv)
    return found


def choose_mrva(candidates: List[Tuple[DpsFile, bool]], mode: str,
                prod_realtime: Optional[bool]) -> Optional[Tuple[DpsFile, bool]]:
    """The MAAP mrva run to compare: latest of the wanted kind."""
    if mode == "nrt":
        want = True
    elif mode == "rea":
        want = False
    else:
        want = prod_realtime
    pool = [c for c in candidates if want is None or c[1] == want]
    if not pool:
        pool = candidates
    return max(pool, key=lambda c: c[0].ts) if pool else None


# --- HTML report ----------------------------------------------------------

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1b;--muted:#6b6b66;--line:#e3e2dd;
--ok:#1f7a4d;--ok-bg:#e3f3ea;--bad:#b3261e;--bad-bg:#fbe7e5;--warn:#8a5a00;
--warn-bg:#fdf1d6;--accent:#2f5d8a;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--fg:#ecebe6;
--muted:#9a9993;--line:#33322f;--ok:#6fcf9c;--ok-bg:#183326;--bad:#f2948c;
--bad-bg:#3a1c19;--warn:#f0c46a;--warn-bg:#352a12;--accent:#8db7e0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
gap:12px;margin-bottom:28px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .k{color:var(--muted);font-size:13px}.card .v{font-size:26px;font-weight:600}
.card.ok .v{color:var(--ok)}.card.bad .v{color:var(--bad)}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;margin-bottom:20px}
.what{color:var(--muted);font-size:13.5px;margin:0 0 12px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:500;font-size:12.5px;text-transform:uppercase;letter-spacing:.03em}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
tr.diff td{background:var(--bad-bg)}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.bad{background:var(--bad-bg);color:var(--bad)}
.pill.na{background:var(--line);color:var(--muted)}
.warn{background:var(--warn-bg);color:var(--warn);border-radius:8px;padding:10px 12px;
margin:10px 0;font-size:13.5px}
code,.mono{font-family:var(--mono);font-size:12.5px;word-break:break-all;white-space:normal}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:0}
dt{color:var(--muted);font-size:13px}dd{margin:0}
details{margin:8px 0}summary{cursor:pointer;color:var(--accent);font-size:13.5px}
ul.names{columns:2 340px;margin:6px 0 0;padding-left:18px}
ul.names li{font-family:var(--mono);font-size:12px}
.side{font-weight:600;font-size:12.5px;margin-top:8px}
"""


def _e(value) -> str:
    import html
    return html.escape("" if value is None else str(value))


def _pill(ok: Optional[bool], yes="match", no="differs", na="n/a") -> str:
    if ok is None:
        return f'<span class="pill na">{na}</span>'
    return (f'<span class="pill ok">{yes}</span>' if ok
            else f'<span class="pill bad">{no}</span>')


def _num(v) -> str:
    return "&ndash;" if v is None else f"{v:,}"


def _names(title: str, names: List[str]) -> str:
    if not names:
        return ""
    items = "".join(f"<li>{_e(n)}</li>" for n in names)
    return f'<div class="side">{_e(title)} ({len(names)})</div><ul class="names">{items}</ul>'


def render_html(report: Dict) -> str:
    """A self-contained page from the report dict -- the same data as
    report.json, so the two cannot disagree."""
    diffs = report.get("differences", {})
    ing = report.get("mrva_ingest", {})
    labels = {"mrva_ingest": "MRVA ingest", "l2p": "L2P → BIC",
              "landice": "Land/ice", "iquam": "iQUAM"}
    kind = lambda rt: "&ndash;" if rt is None else ("NRT" if rt else "REA")

    cards = "".join(
        f'<div class="card {"ok" if not n else "bad"}"><div class="k">{labels.get(k, k)}</div>'
        f'<div class="v">{n}</div><div class="k">difference{"" if n == 1 else "s"}</div></div>'
        for k, n in diffs.items())

    # MRVA ingest
    rows = []
    for r in ing.get("rows", []):
        delta = (r["maap"] - r["prod"]) if None not in (r["maap"], r["prod"]) else None
        pct = (f"{100 * delta / r['prod']:+.2f}%" if delta and r["prod"] else "")
        rows.append(
            f'<tr class="{"" if r["match"] else "diff"}"><td>{_e(r["sensor"])}</td>'
            f'<td>{r["year"]}/{r["doy"]:03d}</td>'
            f'<td class="n">{_num(r["prod"])}</td><td>{_e(r["prod_note"])}</td>'
            f'<td class="n">{_num(r["maap"])}</td><td>{_e(r["maap_note"])}</td>'
            f'<td class="n">{"" if delta is None else f"{delta:+,}"}</td>'
            f'<td class="n">{pct}</td><td>{_pill(r["match"])}</td></tr>')
    cands = "".join(
        f'<tr><td>{_e(c["when"])}</td><td>{kind(c["realtime"])}</td>'
        f'<td class="mono">{_e(c["job"])}</td></tr>' for c in ing.get("candidates", []))
    mismatch_kind = (ing.get("prod_realtime") is not None
                     and ing.get("maap_realtime") is not None
                     and ing["prod_realtime"] != ing["maap_realtime"])
    ingest_html = f"""
<section><h2>MRVA ingest</h2>
<p class="what">Points per sensor and day that <code>makebiq.m</code> actually read,
from <code>&lt;YYYYMMDD&gt;09_MRVA4_Global_inputs.txt</code> on each side. This is
what the analysis saw, not just what it was handed.</p>
<dl><dt>prod</dt><dd class="mono">{_e(ing.get("prod_file"))} &middot; {kind(ing.get("prod_realtime"))}</dd>
<dt>MAAP</dt><dd class="mono">{_e(ing.get("maap_job") or "no MRVA run found")}
{"&middot; " + kind(ing.get("maap_realtime")) + " &middot; " + _e(ing.get("maap_when")) if ing.get("maap_job") else ""}</dd></dl>
{'<div class="warn">MAAP has no run of the same kind as prod&rsquo;s file, so point counts can differ for that reason alone.</div>' if mismatch_kind else ""}
<div class="scroll"><table><thead><tr><th>Sensor</th><th>Day</th><th class="n">Prod</th><th></th>
<th class="n">MAAP</th><th></th><th class="n">Δ</th><th class="n">Δ%</th><th></th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="9">No ingest log on either side.</td></tr>'}</tbody></table></div>
{f'<details><summary>All MAAP MRVA runs for this day ({len(ing.get("candidates", []))})</summary><div class="scroll"><table><thead><tr><th>Started</th><th>Kind</th><th>Job directory</th></tr></thead><tbody>{cands}</tbody></table></div></details>' if cands else ""}
</section>"""

    # MRVA params
    params = report.get("mrva_params") or {}
    if params:
        plist = "".join(f"<dt>{_e(k)}</dt><dd class='mono'>{_e(params[k])}</dd>"
                        for k in MRVA_PARAMS if k in params)
        bootstrap = ("" if params.get("prior_csp_file") else
                     '<div class="warn"><strong>No <code>prior_csp_file</code>.</strong> '
                     "This MRVA bootstrapped instead of chaining from the previous day&rsquo;s "
                     "coefficients, which prod always does. That alone changes the analysis.</div>")
        params_html = (f'<section><h2>MRVA job parameters (MAAP)</h2>{bootstrap}'
                       f'<dl>{plist}</dl></section>')
    else:
        params_html = ('<section><h2>MRVA job parameters (MAAP)</h2><p class="what">'
                       "Could not read the job&rsquo;s parameters from _job.json / "
                       "_context.json.</p></section>")

    # L2P
    l2p_rows, l2p_details = [], []
    for r in report.get("l2p", []):
        differs = bool(r["only_prod"] or r["only_maap"])
        maap_missing = not r["maap_versions"]
        status = (_pill(None, na="prod missing") if r["prod_missing"] else
                  _pill(None, na="MAAP missing") if maap_missing else _pill(not differs))
        day = f'{r["year"]}/{r["doy"]:03d}'
        l2p_rows.append(
            f'<tr class="{"diff" if differs else ""}"><td>{_e(r["sensor"])}</td><td>{day}</td>'
            f'<td class="n">{"&ndash;" if r["prod_missing"] else r["prod"]}</td>'
            f'<td class="n">{"&ndash;" if maap_missing else r["maap"]}</td>'
            f'<td class="n">{r["common"]}</td><td class="n">{len(r["only_prod"])}</td>'
            f'<td class="n">{len(r["only_maap"])}</td><td>{status}</td>'
            f'<td>{_e(r.get("note", ""))}</td></tr>')
        if differs:
            l2p_details.append(
                f'<details><summary>{_e(r["sensor"])} {day}: '
                f'{len(r["only_prod"])} only in prod, {len(r["only_maap"])} only on MAAP'
                f'</summary>{_names("Only in prod", r["only_prod"])}'
                f'{_names("Only on MAAP", r["only_maap"])}</details>')
    l2p_html = f"""
<section><h2>L2P granules per BIC</h2>
<p class="what">Granules folded into each BIC, from <code>L2Plist_*.txt</code>, over every
sensor and the &plusmn;dayrange window. MAAP&rsquo;s latest version is compared with
prod&rsquo;s (both keep only their final one); the notes say when MRVA read an older one.</p>
<div class="scroll"><table><thead><tr><th>Sensor</th><th>Day</th><th class="n">Prod</th>
<th class="n">MAAP</th><th class="n">Common</th><th class="n">Only prod</th>
<th class="n">Only MAAP</th><th></th><th>MAAP versions</th></tr></thead>
<tbody>{"".join(l2p_rows)}</tbody></table></div>{"".join(l2p_details)}</section>"""

    # Land/ice
    ice = report.get("landice", {})
    ice_ok = None if not (ice.get("prod") and ice.get("maap")) else not (
        ice["only_prod"] or ice["only_maap"])
    ice_html = f"""
<section><h2>Land/ice {_pill(ice_ok, na="incomplete")}</h2>
<p class="what">OSI-SAF files used, from <code>icefiles_YYYY_DDD.txt</code>.</p>
<dl><dt>prod</dt><dd class="mono">{_e(ice.get("prod_file") or "missing")} &middot; {ice.get("prod", 0)} files</dd>
<dt>MAAP</dt><dd class="mono">{_e(ice.get("maap_key"))} &middot; {ice.get("maap", 0)} files</dd>
<dt>common</dt><dd>{ice.get("common", 0)}</dd></dl>
{_names("Only in prod", ice.get("only_prod", []))}{_names("Only on MAAP", ice.get("only_maap", []))}
</section>"""

    # iQUAM
    iq_rows = "".join(
        f'<tr class="{"" if r["match"] else "diff"}"><td>{r["year"]}/{r["doy"]:03d}</td>'
        f'<td class="n">{_num(r["prod"])}</td><td class="n">{_num(r["maap"])}</td>'
        f'<td>{_pill(r["match"])}</td></tr>' for r in report.get("iquam", []))
    iquam_html = f"""
<section><h2>iQUAM</h2>
<p class="what">Size in bytes of each <code>.bii</code> over the buoy window. iQUAM writes
no input list, so size is the cheapest check that both sides built the same file.</p>
<div class="scroll"><table><thead><tr><th>Day</th><th class="n">Prod</th><th class="n">MAAP</th>
<th></th></tr></thead><tbody>{iq_rows}</tbody></table></div></section>"""

    title = f'Inputs {report["year"]}/{report["doy"]:03d}'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAAP vs Prod {_e(title)}</title><style>{CSS}</style></head>
<body><main>
<h1>MAAP vs production inputs &middot; {_e(report["date"])}</h1>
<p class="sub">Analysis day {report["year"]}/{report["doy"]:03d} &middot; prod host
{_e(report.get("host") or "not read (--skip-remote)")} &middot; generated {_e(report.get("generated"))}</p>
<div class="cards">{cards}</div>
{ingest_html}{params_html}{l2p_html}{ice_html}{iquam_html}
</main></body></html>
"""


# --- driver ---------------------------------------------------------------

def day_window(center: datetime.date, half: int) -> List[datetime.date]:
    return [center + datetime.timedelta(days=o) for o in range(-half, half + 1)]


def yd(d: datetime.date) -> Tuple[int, int]:
    return d.year, d.timetuple().tm_yday


def save(out: pathlib.Path, rel: str, text: Optional[str]) -> None:
    if text is None:
        return
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--date", type=datetime.date.fromisoformat,
                    help="analysis day, YYYY-MM-DD")
    ap.add_argument("--year", type=int)
    ap.add_argument("--doy", type=int)
    ap.add_argument("--host", help="ssh target for the prod side, e.g. "
                    "podaac-mure or user@podaac-ops-measures")
    ap.add_argument("--ssh-opt", action="append", default=[],
                    help="extra ssh argument; repeat for each, e.g. "
                         "--ssh-opt -p --ssh-opt 2222")
    ap.add_argument("--skip-remote", action="store_true",
                    help="MAAP side only (no ssh)")
    ap.add_argument("--mode", choices=("auto", "nrt", "rea"), default="auto",
                    help="which MAAP mrva run to compare (default: match prod)")
    ap.add_argument("--sensors", help="comma list (default: prod's "
                    + ",".join(s for s, _ in prod.SENSORS) + ")")
    ap.add_argument("--bic-root", default=prod.BIC_ROOT)
    ap.add_argument("--csp-root", default=prod.CSP_ROOT)
    ap.add_argument("--iquam-root", default=prod.IQUAM_ROOT)
    ap.add_argument("--landice-roots", default=",".join(
                    (prod.LANDICE_P011_ROOT, prod.LANDICE_P01_ROOT)),
                    help="comma list searched in order for icefiles_*.txt")
    ap.add_argument("--out", type=pathlib.Path,
                    help="where raw files and report.json go "
                         "(default: ./maap_vs_prod_<YYYY>_<DDD>)")
    ap.add_argument("--max-names", type=int, default=15,
                    help="granule names to print per difference (all go to JSON)")
    args = ap.parse_args(argv)
    if args.date is None:
        if args.year is None or args.doy is None:
            ap.error("give --date, or --year and --doy")
        args.date = datetime.date(args.year, 1, 1) + datetime.timedelta(days=args.doy - 1)
    if not args.skip_remote and not args.host:
        ap.error("--host is required unless --skip-remote")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    day = args.date
    year, doy = yd(day)
    out = args.out or pathlib.Path(f"maap_vs_prod_{year}_{doy:03d}")
    out.mkdir(parents=True, exist_ok=True)

    dayranges = dict(prod.SENSORS)
    sensors = args.sensors.split(",") if args.sensors else list(dayranges)
    bic_days = {s: day_window(day, dayranges.get(s, 2)) for s in sensors}
    iquam_days = day_window(day, prod.BUOY_DAYRANGE)
    csp_body = f"{day:%Y%m%d}09_MRVA4_Global"
    inputs_name = f"{csp_body}_inputs.txt"

    # Remote paths, in prod's layout.
    remote_l2plist = {
        (s, d): f"{args.bic_root}/{s}/{d.year}/L2Plist_Global_{s}_{yd(d)[0]}_{yd(d)[1]:03d}.txt"
        for s in sensors for d in bic_days[s]}
    remote_inputs = f"{args.csp_root}/{year}/{inputs_name}"
    remote_icefiles = [f"{root}/{year}/icefiles_{year}_{doy:03d}.txt"
                       for root in args.landice_roots.split(",") if root]
    remote_bii = {d: f"{args.iquam_root}/{d.year}/Global_IQUAM0_{yd(d)[0]}_{yd(d)[1]:03d}.bii"
                  for d in iquam_days}

    # Remote first: it may prompt for a password, and --mode auto needs it.
    r_text: Dict[str, Optional[str]] = {}
    r_size: Dict[str, Optional[int]] = {}
    if not args.skip_remote:
        dump = fetch_remote(args.host, args.ssh_opt, remote_script(
            [remote_inputs, *remote_icefiles, *remote_l2plist.values()],
            list(remote_bii.values())))
        r_text, r_size = parse_remote_dump(dump)
        for path, text in r_text.items():
            save(out / "prod", path.lstrip("/"), text)

    print(f"Listing MAAP DPS outputs for {day} ({year}/{doy:03d})")
    maap = Maap()
    report: Dict = {"date": str(day), "year": year, "doy": doy,
                    "host": None if args.skip_remote else args.host}

    # --- MRVA ingest ------------------------------------------------------
    prod_inputs = r_text.get(remote_inputs)
    prod_rt, prod_rows = (parse_inputs_txt(prod_inputs) if prod_inputs
                          else (None, {}))

    mrva_files = maap.stage_files("mrva")
    candidates = []
    for f in mrva_files:
        if f.name == inputs_name:
            text = maap.text(f.key)
            candidates.append((f, parse_inputs_txt(text or "")[0], text))
    print(f"\n== MRVA ingest ({inputs_name}) ==")
    print(f"  prod: {remote_inputs}  "
          + ("[MISSING]" if prod_inputs is None else ("[NRT]" if prod_rt else "[REA]")))
    for f, rt, _ in sorted(candidates, key=lambda c: c[0].ts):
        print(f"  maap candidate: {f.when}  {'NRT' if rt else 'REA'}  {f.job}")
    chosen = choose_mrva([(f, rt) for f, rt, _ in candidates], args.mode, prod_rt)
    mrva_job = chosen[0] if chosen else None
    maap_rows: Dict = {}
    if mrva_job is None:
        print("  maap: no mrva job staged out this day's inputs.txt")
    else:
        text = next(t for f, _, t in candidates if f is mrva_job)
        _, maap_rows = parse_inputs_txt(text or "")
        print(f"  comparing maap run {mrva_job.when} "
              f"[{'NRT' if chosen[1] else 'REA'}]")
        if prod_rt is not None and chosen[1] != prod_rt:
            print("  WARNING: MAAP has no run of the same kind as prod's file; "
                  "point counts will differ for that reason alone")
        save(out / "maap" / "mrva", inputs_name, text)
        # The rest of the job's small text files: logs, _job.json, context.
        for f in mrva_files:
            if f.job == mrva_job.job and "/" not in f.rel and (
                    f.rel.endswith((".txt", ".json", ".log")) or "std" in f.rel):
                save(out / "maap" / "mrva" / "job", f.rel, maap.text(f.key))

    ingest = []
    print(f"  {'SENSOR':<8} {'DAY':<9} {'PROD':>10} {'MAAP':>10}")
    for key in sorted(set(prod_rows) | set(maap_rows)):
        p = prod_rows.get(key, (None, ""))
        m = maap_rows.get(key, (None, ""))
        same = p[0] == m[0]
        ingest.append({"sensor": key[0], "year": key[1], "doy": key[2],
                       "prod": p[0], "prod_note": p[1],
                       "maap": m[0], "maap_note": m[1], "match": same})
        fmt = lambda v: "-" if v[0] is None else f"{v[0]}{'*' if v[1] else ''}"
        print(f"  {key[0]:<8} {key[1]}/{key[2]:03d} {fmt(p):>10} {fmt(m):>10}"
              + ("" if same else "   <-- differs"))
    if any(r["prod_note"] or r["maap_note"] for r in ingest):
        print("  (* = 0 points with a reason: no file / no content / invalid)")
    report["mrva_ingest"] = {"prod_file": remote_inputs, "prod_realtime": prod_rt,
                             "maap_job": mrva_job.job if mrva_job else None,
                             "maap_realtime": chosen[1] if chosen else None,
                             "maap_when": mrva_job.when if mrva_job else None,
                             "candidates": [
                                 {"when": f.when, "realtime": rt, "job": f.job}
                                 for f, rt, _ in sorted(candidates,
                                                        key=lambda c: c[0].ts)],
                             "rows": ingest}

    # --- MRVA parameters --------------------------------------------------
    params = {}
    if mrva_job:
        for f in mrva_files:
            if f.job == mrva_job.job and (f.name in ("_job.json", "_context.json")
                                         or f.name.endswith(".context.json")):
                try:
                    params.update({k: v for k, v in find_params(
                        json.loads(maap.text(f.key) or "{}")).items()
                        if k not in params})
                except json.JSONDecodeError:
                    pass
        print("\n== MRVA job parameters (MAAP) ==")
        if not params:
            print("  could not read the job's parameters from its _job.json/*.context.json")
        for k in MRVA_PARAMS:
            if k in params:
                print(f"  {k:<28} {params[k]}")
        if params and not params.get("prior_csp_file"):
            print("  WARNING: no prior_csp_file -- this MRVA BOOTSTRAPPED instead "
                  "of chaining from the previous day's coefficients, unlike prod")
    report["mrva_params"] = params

    manifest_key = maap.workspace_key(f"mur/manifests/mrva/{year}/{doy:03d}.json")
    save(out / "maap" / "manifests", f"mrva_{year}_{doy:03d}.json", maap.text(manifest_key))

    # --- L2P -> BIC -------------------------------------------------------
    print("\n== L2P granules per BIC (L2Plist) ==")
    l2p_files = maap.stage_files("l2p")
    print(f"  {'SENSOR':<8} {'DAY':<9} {'PROD':>6} {'MAAP':>6} {'ONLY-P':>7} "
          f"{'ONLY-M':>7}  MAAP VERSIONS")
    l2p_report = []
    for s in sensors:
        for d in bic_days[s]:
            y, dd = yd(d)
            rx = re.compile(rf"^L2Plist_\w+_{re.escape(s)}_{y}_{dd:03d}\.txt$")
            versions = sorted((f for f in l2p_files if rx.match(f.name)),
                              key=lambda f: f.ts)
            latest = versions[-1] if versions else None
            used = None
            if mrva_job:
                before = [f for f in versions if f.ts <= mrva_job.ts]
                used = before[-1] if before else None

            prod_text = r_text.get(remote_l2plist[(s, d)])
            maap_text = maap.text(latest.key) if latest else None
            if latest:
                save(out / "maap" / "l2p", latest.name, maap_text)
            row = {"sensor": s, "year": y, "doy": dd,
                   "prod_file": remote_l2plist[(s, d)],
                   "prod_missing": prod_text is None and not args.skip_remote,
                   "maap_versions": [v.when for v in versions],
                   "maap_latest_job": latest.job if latest else None,
                   "maap_used_by_mrva_job": used.job if used else None}
            row.update(diff_names(file_names(prod_text or ""),
                                  file_names(maap_text or "")))
            note = f"{len(versions)}"
            if used is not None and used is not latest:
                used_names = file_names(maap.text(used.key) or "")
                row["used_by_mrva"] = diff_names(file_names(maap_text or ""), used_names)
                row["used_by_mrva"]["count"] = len(set(used_names))
                note += (f"; MRVA read an older one ({used.when}, "
                         f"{len(set(used_names))} granules)")
            elif mrva_job and versions and used is None:
                note += "; all written AFTER the mrva job started"
            row["note"] = note
            l2p_report.append(row)
            p_n = "MISSING" if row["prod_missing"] else str(row["prod"])
            m_n = "MISSING" if latest is None else str(row["maap"])
            flag = "" if not (row["only_prod"] or row["only_maap"]) else "  <--"
            print(f"  {s:<8} {y}/{dd:03d} {p_n:>6} {m_n:>6} "
                  f"{len(row['only_prod']):>7} {len(row['only_maap']):>7}  {note}{flag}")
    for row in l2p_report:
        for side in ("only_prod", "only_maap"):
            if row[side]:
                names = row[side]
                print(f"    {row['sensor']} {row['year']}/{row['doy']:03d} {side}: "
                      + ", ".join(names[:args.max_names])
                      + (f" ... (+{len(names) - args.max_names})"
                         if len(names) > args.max_names else ""))
    report["l2p"] = l2p_report

    # --- Land/ice ---------------------------------------------------------
    print("\n== Land/ice (icefiles) ==")
    ice_key = maap.workspace_key(
        f"mur/landice/p011/{year}/icefiles_{year}_{doy:03d}.txt")
    maap_ice = maap.text(ice_key)
    prod_ice_path = next((p for p in remote_icefiles if r_text.get(p) is not None), None)
    prod_ice = r_text.get(prod_ice_path) if prod_ice_path else None
    save(out / "maap" / "landice", f"icefiles_{year}_{doy:03d}.txt", maap_ice)
    ice = diff_names(file_names(prod_ice or ""), file_names(maap_ice or ""))
    ice.update(prod_file=prod_ice_path, maap_key=ice_key)
    print(f"  prod: {prod_ice_path or 'MISSING (tried ' + ', '.join(remote_icefiles) + ')'}")
    print(f"  maap: s3://{maap.bucket}/{ice_key}" + ("" if maap_ice else "  MISSING"))
    print(f"  {ice['prod']} prod / {ice['maap']} maap / {ice['common']} common")
    for side in ("only_prod", "only_maap"):
        for name in ice[side]:
            print(f"    {side}: {name}")
    report["landice"] = ice

    # --- iQUAM ------------------------------------------------------------
    print("\n== iQUAM .bii sizes (bytes) ==")
    iquam = []
    for d in iquam_days:
        y, dd = yd(d)
        key = maap.workspace_key(f"mur/iquam/{y}/Global_IQUAM0_{y}_{dd:03d}.bii")
        p, m = r_size.get(remote_bii[d]), maap.size(key)
        iquam.append({"year": y, "doy": dd, "prod": p, "maap": m, "match": p == m})
        print(f"  {y}/{dd:03d} {('-' if p is None else p):>12} "
              f"{('-' if m is None else m):>12}" + ("" if p == m else "   <-- differs"))
    report["iquam"] = iquam

    # --- summary ----------------------------------------------------------
    diffs = {
        "mrva_ingest": sum(not r["match"] for r in ingest),
        "l2p": sum(bool(r["only_prod"] or r["only_maap"]) for r in l2p_report),
        "landice": int(bool(ice["only_prod"] or ice["only_maap"])),
        "iquam": sum(not r["match"] for r in iquam),
    }
    report["differences"] = diffs
    report["generated"] = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC")
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "report.html").write_text(render_html(report))
    print("\n== Summary ==")
    for k, v in diffs.items():
        print(f"  {k:<12} {v} difference(s)")
    print(f"\nRaw files, report.json and report.html in {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
