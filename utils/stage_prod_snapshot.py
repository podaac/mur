#!/usr/bin/env python3
"""Bring a prod run snapshot to S3 and turn it into a frozen regression case.

capture_prod_run.py writes the snapshot on the prod side. This runs where both
ssh to prod and MAAP credentials work (your laptop):

  pull    rsync <snap-root>/<YYYYMMDD>/ plus the L2P pool files it references
  verify  check every file against files.json, and every pool file against
          its md5 name
  build   upload to <dest>/<YYYYMMDD>/snapshot/ and <dest>/l2p_pool/, seed
          the isolated and chained data roots by server-side copy, and write
          <dest>/<YYYYMMDD>/case.json for run_mur_maap.py --frozen-case
  all     pull, verify, build

  python utils/stage_prod_snapshot.py all --run-date 2026-10-24 \\
      --host <user>@<capture host> --snap-root /path/to/mur_snapshots \\
      --local ~/mur_snapshots --dest s3://nasa-maap-mur-sst/regression

In S3 a granule lives at l2p_pool/<SENSOR>/<md5>/<name>. It is shared across
cases, and its basename is the granule's real name, which is what the
container's localize_manifest and SensorTable's filename patterns need.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "utils"))

import prod_paths as P  # noqa: E402
from mur_maap import frozen as fz  # noqa: E402

CHUNK = 8 * 1024 * 1024


def md5_file(path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                return h.hexdigest()
            h.update(b)


def stamp(run_date: datetime.date) -> str:
    return run_date.strftime("%Y%m%d")


# --- reading a local snapshot ---------------------------------------------

class LocalSnapshot:
    def __init__(self, local_root, run_date: datetime.date):
        self.root = pathlib.Path(local_root).expanduser()
        self.run_date = run_date
        self.dir = self.root / stamp(run_date)
        self.pool = self.root / "l2p_pool"

    def json(self, rel):
        return json.loads((self.dir / rel).read_text())

    @property
    def run(self) -> Dict:
        return self.json("run.json")

    def day_tags(self) -> List[str]:
        days = self.dir / "days"
        return sorted(p.name for p in days.iterdir() if p.is_dir()) if days.is_dir() else []

    def l2p(self, day_tag) -> Dict:
        p = self.dir / "days" / day_tag / "l2p.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def files(self) -> List[Dict]:
        return self.json("files.json")["files"]

    def pool_refs(self) -> List[Tuple[str, str, str]]:
        """(sensor, name, md5) for every granule any day of the run used."""
        refs = set()
        for t in self.day_tags():
            for sensor, per in self.l2p(t).items():
                for items in per.values():
                    for g in items:
                        if g.get("md5"):
                            refs.add((sensor, g["name"], g["md5"]))
        return sorted(refs)

    def day_files(self) -> Dict[str, List[Tuple[str, str]]]:
        """day tag -> [(rel inside the day, md5)] from files.json."""
        out: Dict[str, List[Tuple[str, str]]] = {}
        for f in self.files():
            parts = f["rel"].split("/", 2)
            if parts[0] == "days" and len(parts) == 3:
                out.setdefault(parts[1], []).append((parts[2], f["md5"]))
        return out


# --- pull / verify ----------------------------------------------------------

def rsync(args: List[str], dry_run=False):
    cmd = ["rsync", "-a", "--partial", *args]
    print("+", " ".join(cmd))
    if not dry_run:
        subprocess.run(cmd, check=True)


def cmd_pull(a):
    snap = LocalSnapshot(a.local, a.run_date)
    snap.dir.mkdir(parents=True, exist_ok=True)
    remote = f"{a.host}:{a.snap_root.rstrip('/')}"
    ssh = ["-e", "ssh " + " ".join(a.ssh_opt)] if a.ssh_opt else []
    rsync([*ssh, f"{remote}/{stamp(a.run_date)}/", f"{snap.dir}/"], a.dry_run)
    run = snap.run
    if run.get("status") != "complete" and not a.allow_partial:
        raise SystemExit(f"snapshot status is {run.get('status')!r}; "
                         f"--allow-partial to stage it anyway")
    refs = snap.pool_refs()
    if refs:
        listing = snap.dir / ".pool-files.txt"
        listing.write_text("".join(f"{s}/{n}/{m}\n" for s, n, m in refs))
        rsync([*ssh, f"--files-from={listing}", f"{remote}/l2p_pool/", f"{snap.pool}/"],
              a.dry_run)
    print(f"pulled {snap.dir} and {len(refs)} pool file(s)")
    return 0


def verify(snap: LocalSnapshot, jobs=8) -> List[str]:
    """Problems found, empty when every byte is what prod hashed."""
    checks = [(snap.dir / f["rel"], f["md5"], f["rel"]) for f in snap.files()]
    checks += [(snap.pool / s / n / m, m, f"l2p_pool/{s}/{n}") for s, n, m in snap.pool_refs()]

    def one(item):
        path, want, label = item
        if not path.is_file():
            return f"missing: {label}"
        got = md5_file(path)
        return None if got == want else f"md5 differs: {label} ({got} != {want})"

    with concurrent.futures.ThreadPoolExecutor(jobs) as ex:
        return [p for p in ex.map(one, checks) if p]


def cmd_verify(a):
    problems = verify(LocalSnapshot(a.local, a.run_date))
    for p in problems:
        print("  " + p)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


# --- the case -------------------------------------------------------------

def pool_href(dest: str, sensor: str, name: str, md5: str) -> str:
    return f"{dest.rstrip('/')}/l2p_pool/{sensor}/{md5}/{name}"


def granule_map(snap: LocalSnapshot, dest: str) -> Tuple[Dict, List[Dict]]:
    """sensor -> BIC day tag -> [pool hrefs], plus the conflicts and gaps.

    Within one run prod builds each BIC once (nrtMRVA.py's "just written"
    check), so every day's L2Plist for a given BIC normally agrees. When they
    do not, the earliest day wins, the same rule as fz.seed_plan.
    """
    out: Dict[str, Dict[str, List[str]]] = {}
    notes: List[Dict] = []
    for t in snap.day_tags():
        for sensor, per in snap.l2p(t).items():
            for bic_day, items in per.items():
                missing = [g["name"] for g in items if not g.get("md5")]
                if missing:
                    notes.append({"kind": "granule-missing-at-capture", "day": t,
                                  "sensor": sensor, "bic_day": bic_day,
                                  "names": missing})
                hrefs = [pool_href(dest, sensor, g["name"], g["md5"])
                         for g in items if g.get("md5")]
                have = out.setdefault(sensor, {}).get(bic_day)
                if have is None:
                    out[sensor][bic_day] = hrefs
                elif have != hrefs:
                    notes.append({"kind": "l2plist-changed-within-run", "day": t,
                                  "sensor": sensor, "bic_day": bic_day})
    return out, notes


def bic_conflicts(day_files: Dict[str, List[Tuple[str, str]]]) -> List[Dict]:
    seen: Dict[str, Tuple[str, str]] = {}
    out = []
    for t in sorted(day_files):
        for rel, md5 in day_files[t]:
            if rel in seen and seen[rel][1] != md5:
                out.append({"kind": "input-changed-within-run", "file": rel,
                            "first_day": seen[rel][0], "day": t})
            seen.setdefault(rel, (t, md5))
    return out


def prod_outputs(snap: LocalSnapshot, snap_href: str) -> Dict[str, Dict]:
    """Day tag -> hrefs of prod's own outputs, for the compare step."""
    out: Dict[str, Dict] = {}
    for f in snap.files():
        parts = f["rel"].split("/")
        if parts[0] != "outputs":
            continue
        t, kind = parts[1], parts[2]
        href = f"{snap_href}/{f['rel']}"
        d = out.setdefault(t, {"csp": {}, "l4": {}, "caches": {}, "logs": {}})
        name = parts[-1]
        if kind == "csp":
            if name.endswith("_inputs.txt"):
                d["inputs_txt"] = href
            else:
                d["csp"][name.rsplit(".", 1)[-1]] = href
        elif kind == "l4":
            d["l4"][parts[3]] = href
        elif kind in ("caches", "logs"):
            d[kind][name] = href
    return out


def build_case(snap: LocalSnapshot, dest: str) -> Tuple[Dict, Dict[str, Dict[str, str]]]:
    """case.json, and the {variant: {root key: snapshot rel}} seeding plan."""
    run = snap.run
    case_root = f"{dest.rstrip('/')}/{stamp(snap.run_date)}"
    snap_href = f"{case_root}/snapshot"
    granules, notes = granule_map(snap, dest)
    day_files = snap.day_files()
    notes += bic_conflicts(day_files)
    plan = fz.seed_plan(day_files, P.STABLAT, snap.run_date)
    days = {t: {"date": v["date"], "mode": v["mode"]}
            for t, v in run["days"].items() if t in day_files}
    case = {
        "schema": fz.SCHEMA,
        "run_date": run["run_date"],
        "exact": run.get("exact", False),
        "source": {"host": run.get("host"), "snapshot": snap_href,
                   "captured": run.get("finished_at"),
                   "nrtMRVA_py_md5": run.get("nrtMRVA_py_md5"),
                   "cyc4_md5": (run.get("cyc4_code") or {}).get("md5")},
        "days": days,
        "granules": granules,
        "roots": {v: f"{case_root}/{v}" for v in fz.VARIANTS},
        "prod": prod_outputs(snap, snap_href),
        "notes": notes,
    }
    return case, plan


# --- upload ---------------------------------------------------------------

class S3:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        if dry_run:
            self.s3 = None
            return
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

    def size(self, uri) -> Optional[int]:
        if self.dry_run:
            return None
        b, k = self.split(uri)
        try:
            return self.s3.head_object(Bucket=b, Key=k)["ContentLength"]
        except Exception:                                  # noqa: BLE001
            return None

    def put_file(self, path, uri):
        if self.size(uri) == os.path.getsize(path):
            return False
        if not self.dry_run:
            b, k = self.split(uri)
            self.s3.upload_file(str(path), b, k)
        return True

    def put_json(self, obj, uri):
        print("  write", uri)
        if not self.dry_run:
            b, k = self.split(uri)
            self.s3.put_object(Bucket=b, Key=k, ContentType="application/json",
                               Body=json.dumps(obj, indent=1, sort_keys=True).encode())

    def copy(self, src, dest):
        if not self.dry_run:
            sb, sk = self.split(src)
            db, dk = self.split(dest)
            self.s3.copy_object(Bucket=db, Key=dk, CopySource={"Bucket": sb, "Key": sk})


def upload_all(s3: S3, jobs: List[Tuple[pathlib.Path, str]], workers=8) -> int:
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        return sum(ex.map(lambda j: s3.put_file(*j), jobs))


def cmd_build(a):
    snap = LocalSnapshot(a.local, a.run_date)
    if not a.skip_verify:
        problems = verify(snap)
        if problems:
            raise SystemExit(f"{len(problems)} file(s) fail verification; run "
                             f"`verify` to list them")
    case, plan = build_case(snap, a.dest)
    case_root = f"{a.dest.rstrip('/')}/{stamp(a.run_date)}"
    s3 = S3(dry_run=a.dry_run)

    files = [(snap.dir / f["rel"], f"{case_root}/snapshot/{f['rel']}") for f in snap.files()]
    for extra in ("run.json", "files.json", "logs/nrtMRVA.log"):
        if (snap.dir / extra).exists():
            files.append((snap.dir / extra, f"{case_root}/snapshot/{extra}"))
    for t in snap.day_tags():
        for name in ("trigger.json", "l2p.json"):
            p = snap.dir / "days" / t / name
            if p.exists():
                files.append((p, f"{case_root}/snapshot/days/{t}/{name}"))
    print(f"uploading {len(files)} snapshot file(s)")
    n = upload_all(s3, files)
    pool = [(snap.pool / s / nm / m, pool_href(a.dest, s, nm, m)) for s, nm, m in snap.pool_refs()]
    print(f"uploading {len(pool)} pool granule(s) (already present are skipped)")
    n += upload_all(s3, pool)
    print(f"  {n} object(s) sent")

    for variant, keys in plan.items():
        root = case["roots"][variant]
        print(f"seeding {variant}: {len(keys)} object(s) -> {root}")
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda kv: s3.copy(f"{case_root}/snapshot/{kv[1]}", f"{root}/{kv[0]}"),
                        keys.items()))
    s3.put_json(case, f"{case_root}/case.json")
    for note in case["notes"]:
        print("  note:", json.dumps(note))
    print(f"\ncase ready: {case_root}/case.json")
    print(f"  python utils/regress_mur_maap.py run --case {case_root}/case.json "
          f"--config config.maap.json --variant both")
    return 0


def cmd_all(a):
    cmd_pull(a)
    if not a.dry_run:
        problems = verify(LocalSnapshot(a.local, a.run_date))
        if problems:
            for p in problems[:20]:
                print("  " + p)
            raise SystemExit(f"{len(problems)} problem(s); not uploading")
    a.skip_verify = True
    return cmd_build(a)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--run-date", required=True, type=datetime.date.fromisoformat,
                       help="the day nrtMRVA.py ran (the snapshot's name)")
        p.add_argument("--local", default="~/mur_snapshots",
                       help="local snapshot root (default: %(default)s)")
        p.add_argument("--dry-run", action="store_true")

    def remote(p):
        p.add_argument("--host", default=os.environ.get("MUR_PROD_HOST"),
                       required=not os.environ.get("MUR_PROD_HOST"),
                       help="ssh target of the capture host, e.g. user@host "
                            "(default: $MUR_PROD_HOST)")
        p.add_argument("--snap-root", required=True,
                       help="capture_prod_run.py's --snap-root on the prod host")
        p.add_argument("--ssh-opt", action="append", default=[],
                       help="extra ssh option, repeatable")
        p.add_argument("--allow-partial", action="store_true")

    def dest(p):
        p.add_argument("--dest", default="s3://nasa-maap-mur-sst/regression",
                       help="S3 prefix for cases and the shared pool "
                            "(default: %(default)s)")
        p.add_argument("--skip-verify", action="store_true")

    for name, fn, extra in (("pull", cmd_pull, [remote]), ("verify", cmd_verify, []),
                            ("build", cmd_build, [dest]), ("all", cmd_all, [remote, dest])):
        p = sub.add_parser(name)
        common(p)
        for e in extra:
            e(p)
        p.set_defaults(func=fn)
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
