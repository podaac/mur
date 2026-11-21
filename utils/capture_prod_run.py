#!/usr/bin/env python3
"""Snapshot the exact inputs (and outputs) of one production MUR run.

Runs on the prod host, or on any host that mounts its disks (then see
--map and --idle), next to prod_paths.py. Stdlib only.

Why capture as the run goes: every daily run rewrites what the previous one
used. Landice for all nine days, the young BICs and .bii files, and the c06
coefficients of the REA days are all overwritten, and the L2P granules are
purged after 30 days. Within one run each young BIC is built once, by the first
analysis day whose D+-2 window reaches it (nrtMRVA.py:342-345, the
makebiccmd_* "just written" check). But its gzip runs in the background
(writebic.m:34), and a day that arrives before the .gz exists rebuilds it. So
the inputs are copied per analysis day, as that day's MRVA starts.
nrtMRVA.py creates MRVA_<YYYY>_<DDD>.log when it launches mrva4com
(nrtMRVA.py:389-398), which is after that day's BIC/iquam/landice steps, so a
new log is the trigger.

Subcommands:
  watch   start from cron a few minutes before nrtMRVA.py; wait for the run,
          snapshot each day's inputs as its MRVA starts, then the outputs
          once the run (and its background csp2nc4a jobs) has finished
  once    snapshot what is on disk now for a past run date (exact: false;
          young BICs may have been rebuilt by a later run)
  prune   apply --keep to the snapshot root and drop unreferenced pool files

Layout written under --snap-root:
  <YYYYMMDD>/run.json                  run date, days and modes, code hashes, status
  <YYYYMMDD>/files.json                every captured file: src, size, md5, mtime
  <YYYYMMDD>/days/<YYYY_DDD>/          the inputs as that day's MRVA saw them
      trigger.json  bic/  iquam/  landice/p011/  landice/p01/  csp_prior/  l2p.json
  <YYYYMMDD>/outputs/<YYYY_DDD>/       csp/  l4/1km/  l4/25km/  caches/  logs/
  l2p_pool/<SENSOR>/<granule name>/<md5>   granule bytes, shared across runs

Granules are copied from the server's own download tree (never re-fetched):
a name does not pin content (redeliveries, RT->final), and the server purges
L2P after 30 days. A name seen again with a different md5 is kept beside the
first one and counted in run.json, which shows how often it happens.

Safety: nothing is ever written under an ops path; errors are logged and the
process exits 0 so it can never break the cron line it sits on.

Example cron line (same crontab host clock as nrtMRVA.py at 07:05):
  00 07 * * *  nice -n 19 /usr/bin/python3.12 ~/mur/utils/capture_prod_run.py \
      watch --snap-root /path/to/mur_snapshots --keep 14 >> ~/logs/capture.log 2>&1
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prod_paths as P  # noqa: E402

CHUNK = 8 * 1024 * 1024
SNAP_DIR_RE = re.compile(r"^\d{8}$")
TODAY_RE = re.compile(r"Today = Year (\d+) Day (\d+)")
MRVA_LOG_RE = re.compile(r"^MRVA_(\d{4})_(\d{3})\.log$")


def log(*a):
    print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
          *a, flush=True)


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()


def _date(s):
    return datetime.date.fromisoformat(s)


# ---------------------------------------------------------------------------
# Ops path resolution
# ---------------------------------------------------------------------------

class Ops:
    """Maps a prod path (as nrtMRVA.py and the L2Plists name it) to where this
    host reads it.

    `maps` is [(prod prefix, local prefix)], for a host that mounts the ops
    disks somewhere else than the prod host does (--map /nas2=/mnt/nas2).
    The longest matching prefix wins. `fake_root` is for tests and rehearsals
    against a copied tree: every path is then looked up under it.
    """

    def __init__(self, fake_root=None, maps=None):
        self.fake_root = fake_root.rstrip("/") if fake_root else None
        self.maps = sorted(((a.rstrip("/"), b.rstrip("/")) for a, b in (maps or [])),
                           key=lambda ab: -len(ab[0]))

    def __call__(self, path):
        for old, new in self.maps:
            if path == old or path.startswith(old + "/"):
                path = new + path[len(old):]
                break
        if self.fake_root and path.startswith("/") and not path.startswith(self.fake_root + "/"):
            return self.fake_root + path
        return path

    def roots(self):
        return [self(r) for r in (P.BIC_ROOT, P.IQUAM_ROOT, P.LANDICE_P011_ROOT,
                                  P.LANDICE_P01_ROOT, P.CSP_ROOT, P.L4_1KM_ROOT,
                                  P.L4_25KM_ROOT, P.HIRESDT_ROOT, P.MUR25_ICE_ROOT,
                                  P.L2P_ROOT, P.CYC4_CODE_DIR)]


def check_snap_root(ops, snap_root):
    real = os.path.realpath(snap_root)
    for r in ops.roots():
        rr = os.path.realpath(r)
        if real == rr or real.startswith(rr.rstrip("/") + "/"):
            raise SystemExit("refusing --snap-root %s: it is inside ops path %s" % (snap_root, r))


# ---------------------------------------------------------------------------
# File lists
# ---------------------------------------------------------------------------

def day_window(d, half):
    return [d + datetime.timedelta(days=k) for k in range(-half, half + 1)]


def day_input_files(d):
    """(prod path, snapshot-relative path) for everything mrva4com(d) reads
    that changes from day to day. Both .bic and .bic.gz are listed: makebiq
    globs .b* (makebiq.m:169-192) and the gzip runs in the background
    (writebic.m:34), so either can be the one it opened."""
    out = []
    for sensor, half in P.SENSORS:
        for x in day_window(d, half):
            y = x.year
            base = "%s/%s/%d" % (P.BIC_ROOT, sensor, y)
            rel = "bic/%s/%d" % (sensor, y)
            for name in (P.bic_name(sensor, x), P.bic_name(sensor, x) + ".gz",
                         P.l2plist_name(sensor, x)):
                out.append(("%s/%s" % (base, name), "%s/%s" % (rel, name)))
    for x in day_window(d, P.BUOY_DAYRANGE):
        name = P.iquam_name(x)
        out.append(("%s/%d/%s" % (P.IQUAM_ROOT, x.year, name), "iquam/%d/%s" % (x.year, name)))
    y, doy = P.yd(d)
    for name in ("Global_ice_%d_%03d.bip.gz" % (y, doy), "landice_%d_%03d.gds.gz" % (y, doy),
                 "icefiles_%d_%03d.txt" % (y, doy)):
        out.append(("%s/%d/%s" % (P.LANDICE_P011_ROOT, y, name), "landice/p011/%d/%s" % (y, name)))
    for name in ("landiceP01_%d_%03d.gds.gz" % (y, doy), "Global_ice_%d_%03d.bip.gz" % (y, doy)):
        out.append(("%s/%d/%s" % (P.LANDICE_P01_ROOT, y, name), "landice/p01/%d/%s" % (y, name)))
    prev = d - datetime.timedelta(days=1)
    name = P.csp_body(prev) + ".c06"
    out.append(("%s/%d/%s" % (P.CSP_ROOT, prev.year, name), "csp_prior/%d/%s" % (prev.year, name)))
    return out


def day_output_files(ops, d, mode):
    """(prod path, relative path) for what the run wrote for day d. Globs, so
    the result depends on what exists."""
    out = []
    y, doy = P.yd(d)
    cspdir = ops("%s/%d" % (P.CSP_ROOT, y))
    body = P.csp_body(d)
    if os.path.isdir(cspdir):
        for name in sorted(os.listdir(cspdir)):
            if name.startswith((body + ".", body + "_")):
                out.append(("%s/%d/%s" % (P.CSP_ROOT, y, name), "csp/%d/%s" % (y, name)))
    sub = "%03d%s" % (doy, "nrt" if mode == "nrt" else "")
    for root, rel in ((P.L4_1KM_ROOT, "l4/1km"), (P.L4_25KM_ROOT, "l4/25km")):
        top = ops(root)
        if not os.path.isdir(top):
            continue
        for ver in sorted(os.listdir(top)):
            ddir = os.path.join(top, ver, str(y), sub)
            if os.path.isdir(ddir):
                for name in sorted(os.listdir(ddir)):
                    out.append(("%s/%s/%d/%s/%s" % (root, ver, y, sub, name),
                                "%s/%s/%d/%s/%s" % (rel, ver, y, sub, name)))
    out.append(("%s/hiresdt_%d_%03d.grd" % (P.HIRESDT_ROOT, y, doy),
                "caches/hiresdt_%d_%03d.grd" % (y, doy)))
    out.append(("%s/%d/icemap%d_%03d.ice" % (P.MUR25_ICE_ROOT, y, y, doy),
                "caches/icemap%d_%03d.ice" % (y, doy)))
    out.append(("%s/MRVA_%d_%03d.log" % (P.NRT_LOG_DIR, y, doy), "logs/MRVA_%d_%03d.log" % (y, doy)))
    tmplogs = ops(P.MRVA_TMP_LOG_DIR)
    if os.path.isdir(tmplogs):
        key = "%d_%03d" % (y, doy)
        for name in sorted(os.listdir(tmplogs)):
            if key in name:
                out.append(("%s/%s" % (P.MRVA_TMP_LOG_DIR, name), "logs/%s" % name))
    return out


def l2plist_paths(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# Copying
# ---------------------------------------------------------------------------

def copy_hash(src, dest):
    """Copy src to dest (atomically, via a temp name) and return (md5, size)."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    h = hashlib.md5()
    size = 0
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        while True:
            b = fi.read(CHUNK)
            if not b:
                break
            h.update(b)
            fo.write(b)
            size += len(b)
    st = os.stat(src)
    os.utime(tmp, (st.st_atime, st.st_mtime))
    os.replace(tmp, dest)
    return h.hexdigest(), size


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                return h.hexdigest()
            h.update(b)


class Snapshot:
    def __init__(self, snap_root, run_date, ops, dry_run=False):
        self.snap_root = snap_root
        self.run_date = run_date
        self.ops = ops
        self.dry_run = dry_run
        self.dir = os.path.join(snap_root, run_date.strftime("%Y%m%d"))
        self.pool = os.path.join(snap_root, "l2p_pool")
        self.files_path = os.path.join(self.dir, "files.json")
        self.files = self._load(self.files_path, {"files": [], "missing": []})
        self.cache_path = os.path.join(self.pool, ".statcache.json")
        self.statcache = self._load(self.cache_path, {})
        self.pool_stats = {"copied": 0, "reused": 0, "variants": 0, "missing": 0, "bytes": 0}

    @staticmethod
    def _load(path, default):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    def _save(self, path, obj):
        if self.dry_run:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "w") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)

    def save(self):
        self._save(self.files_path, self.files)
        self._save(self.cache_path, self.statcache)

    def grab(self, src, rel):
        """Copy one prod file to <snapshot>/<rel>; record it. Returns the
        files.json entry, or None when the source does not exist."""
        real = self.ops(src)
        now = time.time()
        if not os.path.isfile(real):
            self.files["missing"].append({"src": src, "rel": rel, "checked_at": _iso(now)})
            return None
        st = os.stat(real)
        entry = {"src": src, "rel": rel, "size": st.st_size, "mtime": _iso(st.st_mtime),
                 "captured_at": _iso(now)}
        if self.dry_run:
            log("would copy", src, "->", rel)
            return entry
        md5, size = copy_hash(real, os.path.join(self.dir, rel))
        entry.update(md5=md5, size=size)
        # One entry per path: a re-capture replaces the file and its record.
        self.files["files"] = [f for f in self.files["files"] if f["rel"] != rel]
        self.files["files"].append(entry)
        return entry

    def pool_granule(self, sensor, src):
        """Put one L2P granule into the shared pool, deduplicated by md5."""
        real = self.ops(src)
        name = os.path.basename(src)
        if not os.path.isfile(real):
            self.pool_stats["missing"] += 1
            return {"name": name, "src": src, "missing": True}
        st = os.stat(real)
        key = "%s|%d|%d" % (real, st.st_size, int(st.st_mtime))
        ndir = os.path.join(self.pool, sensor, name)
        md5 = self.statcache.get(key)
        if md5 and os.path.isfile(os.path.join(ndir, md5)):
            self.pool_stats["reused"] += 1
            return {"name": name, "src": src, "md5": md5, "size": st.st_size}
        if self.dry_run:
            log("would pool", src)
            return {"name": name, "src": src, "size": st.st_size}
        tmpdest = os.path.join(ndir, ".incoming")
        md5, size = copy_hash(real, tmpdest)
        final = os.path.join(ndir, md5)
        if os.path.isfile(final):
            os.remove(tmpdest)
            self.pool_stats["reused"] += 1
        else:
            others = [f for f in os.listdir(ndir) if not f.startswith(".")]
            if others:
                self.pool_stats["variants"] += 1
                log("granule content changed under the same name:", sensor, name)
            os.replace(tmpdest, final)
            self.pool_stats["copied"] += 1
            self.pool_stats["bytes"] += size
        self.statcache[key] = md5
        return {"name": name, "src": src, "md5": md5, "size": size}

    # -- per-day captures ------------------------------------------------------

    def capture_day_inputs(self, d, mode, trigger_src=None, with_l2p=True):
        t = P.tag(d)
        rel0 = "days/%s" % t
        log("capturing inputs for", t, mode)
        got = {}
        for src, rel in day_input_files(d):
            got[rel] = self.grab(src, "%s/%s" % (rel0, rel))
        races = sorted(rel[:-3] for rel in got if rel.endswith(".bic.gz")
                       and got[rel] and got.get(rel[:-3]))
        prior = [rel for rel in got if rel.startswith("csp_prior/")]
        l2p = {}
        if with_l2p:
            for sensor, half in P.SENSORS:
                for x in day_window(d, half):
                    src = "%s/%s/%d/%s" % (P.BIC_ROOT, sensor, x.year, P.l2plist_name(sensor, x))
                    try:
                        with open(self.ops(src)) as f:
                            paths = l2plist_paths(f.read())
                    except OSError:
                        continue
                    l2p.setdefault(sensor, {})[P.tag(x)] = [
                        self.pool_granule(sensor, p) for p in paths]
            self._save(os.path.join(self.dir, rel0, "l2p.json"), l2p)
        trig = {
            "day": t, "date": d.isoformat(), "mode": mode,
            "captured_at": _iso(time.time()),
            "trigger": trigger_src,
            "prior_c06": "present" if any(got[r] for r in prior) else "absent",
            "bic_gzip_race": races,
            "missing": sorted(rel for rel, e in got.items() if e is None
                              and not rel.endswith((".bic", ".bic.gz"))),
            "bic_found": sorted(rel for rel, e in got.items() if e and ".bic" in rel),
        }
        self._save(os.path.join(self.dir, rel0, "trigger.json"), trig)
        self.save()
        return trig

    def capture_day_outputs(self, d, mode):
        t = P.tag(d)
        log("capturing outputs for", t, mode)
        n = 0
        for src, rel in day_output_files(self.ops, d, mode):
            if self.grab(src, "outputs/%s/%s" % (t, rel)):
                n += 1
        self.save()
        return n


# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------

def tree_md5(top, exts=(".m", ".f", ".f90", ".py", ".c", ".h", "Makefile", ".nml")):
    """One md5 over the code tree, plus per-file md5s, so a code change in prod
    shows up next to the data it produced."""
    files = {}
    if os.path.isdir(top):
        for dp, dn, fn in os.walk(top):
            dn[:] = [x for x in dn if not x.startswith(".")]
            for name in fn:
                if name.endswith(exts) or name in exts:
                    p = os.path.join(dp, name)
                    try:
                        files[os.path.relpath(p, top)] = md5_file(p)
                    except OSError:
                        pass
    h = hashlib.md5()
    for k in sorted(files):
        h.update(("%s %s\n" % (files[k], k)).encode())
    return {"md5": h.hexdigest() if files else None, "files": files}


def parse_run_header(text):
    """(run_date, first_day, last_day) from the last 'Today = Year Y Day D'
    header nrtMRVA.py writes into nrtMRVA.log (nrtMRVA.py:185-187)."""
    found = None
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = TODAY_RE.search(ln)
        if m:
            today = P.doy_to_date(int(m.group(1)), int(m.group(2)))
            rng = None
            if i + 1 < len(lines):
                m2 = re.search(r"from \((\d+),(\d+)\) to \((\d+),(\d+)\)", lines[i + 1])
                if m2:
                    a, b, c, e = (int(g) for g in m2.groups())
                    rng = (P.doy_to_date(a, b), P.doy_to_date(c, e))
            found = (today, rng)
    if not found:
        return None
    today, rng = found
    if rng is None:
        rng = (today - datetime.timedelta(days=P.SCAN_LATENCY),
               today - datetime.timedelta(days=P.NRT_LATENCY))
    return today, rng[0], rng[1]


def read_from(path, offset):
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _runs(argv, name):
    """Whether a process's argv is running program `name`: as the program
    itself (cron runs the script directly) or as the script an interpreter
    was given. A command that merely mentions it -- `less nrtMRVA.py`, a
    tcsh -c wrapper string, a shell that has it in an argument -- does not
    count."""
    for i, a in enumerate(argv[:2]):
        base = os.path.basename(a)
        if base == name:
            return True
        if i == 0 and not base.startswith(("python", "perl", "bash", "sh")):
            return False
    return False


def processes_matching(name):
    """Command lines of running processes whose program is `name` (Linux
    /proc, falling back to ps)."""
    me = os.getpid()
    out = []
    if os.path.isdir("/proc"):
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or int(pid) == me:
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
            except OSError:
                continue
            if _runs(argv, name):
                out.append(" ".join(argv))
        return out
    try:
        ps = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout
    except OSError:
        return out
    for ln in ps.splitlines():
        pid, _, cmd = ln.strip().partition(" ")
        if pid.isdigit() and int(pid) != me and _runs(cmd.split(), name):
            out.append(cmd)
    return out


def outputs_settled(ops, d, mode, settle_s):
    """True once day d's 1 km L4 file exists and no log for the day under
    /tmp/logs (csp2nc_*, makebiq) has changed for settle_s seconds."""
    y, doy = P.yd(d)
    sub = "%03d%s" % (doy, "nrt" if mode == "nrt" else "")
    top = ops(P.L4_1KM_ROOT)
    have_l4 = False
    if os.path.isdir(top):
        for ver in os.listdir(top):
            ddir = os.path.join(top, ver, str(y), sub)
            if os.path.isdir(ddir) and any(n.endswith(".nc") for n in os.listdir(ddir)):
                have_l4 = True
    if not have_l4:
        return False
    tmplogs = ops(P.MRVA_TMP_LOG_DIR)
    key = "%d_%03d" % (y, doy)
    now = time.time()
    if os.path.isdir(tmplogs):
        for name in os.listdir(tmplogs):
            if key in name:
                try:
                    if now - os.path.getmtime(os.path.join(tmplogs, name)) < settle_s:
                        return False
                except OSError:
                    pass
    return True


def logs_idle(logdir, since, idle_s):
    """True when nrtMRVA.log and every MRVA_*.log written since `since` have
    been unchanged for idle_s seconds."""
    newest = 0.0
    try:
        names = os.listdir(logdir)
    except OSError:
        return False
    for name in names:
        if name == "nrtMRVA.log" or MRVA_LOG_RE.match(name):
            try:
                m = os.path.getmtime(os.path.join(logdir, name))
            except OSError:
                continue
            if m >= since:
                newest = max(newest, m)
    return newest > 0 and time.time() - newest >= idle_s


def offsets(spec):
    """'-4:-1' -> [-4,-3,-2,-1]; '-4,-1' -> [-4,-1]."""
    if ":" in spec:
        a, b = (int(x) for x in spec.split(":"))
        return list(range(min(a, b), max(a, b) + 1))
    return sorted(int(x) for x in spec.split(","))


def base_run_json(args, ops, run_date, first, last, exact):
    days = [run_date + datetime.timedelta(days=k) for k in offsets(args.days)]
    return {
        "schema": 1,
        "host": socket.gethostname(),
        "exact": exact,
        "run_date": run_date.isoformat(),
        "window": [first.isoformat(), last.isoformat()],
        "days": {P.tag(d): {"date": d.isoformat(), "mode": P.mode_for(run_date, d)}
                 for d in days},
        "fake_root": ops.fake_root,
        "nrtMRVA_py_md5": (md5_file(ops(P.NRT_MRVA_SCRIPT))
                           if os.path.isfile(ops(P.NRT_MRVA_SCRIPT)) else None),
        "cyc4_code": tree_md5(ops(P.CYC4_CODE_DIR)),
        "started_at": _iso(time.time()),
        "status": "running",
    }


def write_json(path, obj, dry_run=False):
    if dry_run:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_watch(args):
    ops = Ops(args.fake_root, args.map)
    check_snap_root(ops, args.snap_root)
    logdir = ops(args.log_dir)
    nrtlog = os.path.join(logdir, "nrtMRVA.log")
    since = args.since if args.since is not None else time.time()
    offset = 0 if args.since is not None else file_size(nrtlog)
    t0 = time.time()

    # 1. Wait for the run header so the run date comes from prod's own clock.
    header = None
    while header is None:
        header = parse_run_header(read_from(nrtlog, offset))
        if header:
            break
        if time.time() - t0 > args.start_timeout * 60:
            log("no nrtMRVA run started within %d min; nothing captured" % args.start_timeout)
            return 0
        time.sleep(args.poll)
    run_date, first, last = header
    log("run started: today=%s window %s..%s" % (run_date, first, last))

    snap = Snapshot(args.snap_root, run_date, ops, dry_run=args.dry_run)
    run = base_run_json(args, ops, run_date, first, last, exact=True)
    run_path = os.path.join(snap.dir, "run.json")
    write_json(run_path, run, args.dry_run)
    wanted = {P.tag(_date(v["date"])): (_date(v["date"]), v["mode"]) for v in run["days"].values()}
    done = {}
    seen_process = False
    if not processes_matching(args.process):
        log("cannot see a %s process on this host; the run's end will be taken "
            "from its logs going quiet for %g min" % (args.process, args.idle))

    # 2. Per-day triggers while nrtMRVA.py runs.
    while True:
        try:
            names = sorted(os.listdir(logdir))
        except OSError:
            names = []
        for name in names:
            m = MRVA_LOG_RE.match(name)
            if not m:
                continue
            t = "%s_%s" % (m.group(1), m.group(2))
            if t in done or t not in wanted:
                continue
            if os.path.getmtime(os.path.join(logdir, name)) < since:
                continue
            d, mode = wanted[t]
            done[t] = snap.capture_day_inputs(d, mode, trigger_src=name,
                                              with_l2p=not args.no_l2p)
            run["days"][t]["inputs"] = "captured"
            run["pool"] = snap.pool_stats
            write_json(run_path, run, args.dry_run)
        # The run's end. On the prod host, the nrtMRVA.py process exiting.
        # From another host sharing the disks the process is
        # invisible, so: every wanted day has started and the logs have
        # been quiet for --idle minutes.
        running = processes_matching(args.process)
        if running:
            seen_process = True
        if seen_process:
            if not running:
                break
        elif len(done) == len(wanted) and logs_idle(logdir, since, args.idle * 60):
            break
        if time.time() - t0 > args.timeout * 3600:
            log("timeout waiting for nrtMRVA.py to finish")
            run["timeout"] = True
            break
        time.sleep(args.poll)

    # 3. csp2nc4a runs in the background after each mrva4com (mrva4com.m:421)
    #    and its MATLAB process does not carry a recognisable command line, so
    #    wait until each day's 1 km L4 exists and its csp2nc log has gone quiet.
    t1 = time.time()
    while time.time() - t1 < args.post_timeout * 60:
        pending = [t for t, (d, mode) in wanted.items()
                   if t in done and not outputs_settled(ops, d, mode, args.settle * 60)]
        if not pending:
            break
        time.sleep(args.poll)
    else:
        log("L4 writers still busy after %d min for %s" % (args.post_timeout, pending))
        run["post_timeout"] = pending

    # 4. Outputs, and the nrtMRVA.log section of this run.
    for t, (d, mode) in sorted(wanted.items()):
        if t in done:
            run["days"][t]["outputs"] = snap.capture_day_outputs(d, mode)
        else:
            run["days"][t]["inputs"] = "not triggered"
    if not args.dry_run:
        os.makedirs(os.path.join(snap.dir, "logs"), exist_ok=True)
        with open(os.path.join(snap.dir, "logs", "nrtMRVA.log"), "w") as f:
            f.write(read_from(nrtlog, offset))
    run["pool"] = snap.pool_stats
    run["finished_at"] = _iso(time.time())
    run["status"] = "complete" if len(done) == len(wanted) else "partial"
    write_json(run_path, run, args.dry_run)
    snap.save()
    log("done: %s, %d/%d days, pool %s" % (run["status"], len(done), len(wanted), snap.pool_stats))
    if args.keep:
        prune(args.snap_root, args.keep, args.dry_run)
    return 0


def cmd_once(args):
    ops = Ops(args.fake_root, args.map)
    check_snap_root(ops, args.snap_root)
    run_date = _date(args.run_date)
    first = run_date - datetime.timedelta(days=P.SCAN_LATENCY)
    last = run_date - datetime.timedelta(days=P.NRT_LATENCY)
    snap = Snapshot(args.snap_root, run_date, ops, dry_run=args.dry_run)
    run = base_run_json(args, ops, run_date, first, last, exact=False)
    run["note"] = ("captured after the fact: young BICs, landice and .bii may "
                   "have been rewritten by later runs")
    for t, v in sorted(run["days"].items()):
        d = _date(v["date"])
        snap.capture_day_inputs(d, v["mode"], trigger_src="once", with_l2p=not args.no_l2p)
        v["inputs"] = "captured"
        v["outputs"] = snap.capture_day_outputs(d, v["mode"])
    run["pool"] = snap.pool_stats
    run["finished_at"] = _iso(time.time())
    run["status"] = "complete"
    write_json(os.path.join(snap.dir, "run.json"), run, args.dry_run)
    snap.save()
    log("done:", snap.dir, snap.pool_stats)
    return 0


def referenced_pool(snap_root, keep_dirs):
    refs = set()
    for sd in keep_dirs:
        days = os.path.join(snap_root, sd, "days")
        if not os.path.isdir(days):
            continue
        for t in os.listdir(days):
            try:
                with open(os.path.join(days, t, "l2p.json")) as f:
                    l2p = json.load(f)
            except (OSError, ValueError):
                continue
            for sensor, per in l2p.items():
                for items in per.values():
                    for g in items:
                        if g.get("md5"):
                            refs.add((sensor, g["name"], g["md5"]))
    return refs


def prune(snap_root, keep, dry_run=False):
    dirs = sorted(x for x in os.listdir(snap_root) if SNAP_DIR_RE.match(x))
    drop, kept = dirs[:-keep] if keep else [], dirs[-keep:] if keep else dirs
    for x in drop:
        log("pruning snapshot", x)
        if not dry_run:
            shutil.rmtree(os.path.join(snap_root, x), ignore_errors=True)
    refs = referenced_pool(snap_root, kept)
    pool = os.path.join(snap_root, "l2p_pool")
    removed = 0
    if os.path.isdir(pool):
        for sensor in os.listdir(pool):
            sdir = os.path.join(pool, sensor)
            if not os.path.isdir(sdir):
                continue
            for name in os.listdir(sdir):
                ndir = os.path.join(sdir, name)
                for md5 in os.listdir(ndir):
                    if md5.startswith("."):
                        continue
                    if (sensor, name, md5) not in refs:
                        removed += 1
                        if not dry_run:
                            os.remove(os.path.join(ndir, md5))
                if not dry_run and not [f for f in os.listdir(ndir) if not f.startswith(".")]:
                    shutil.rmtree(ndir, ignore_errors=True)
    log("pruned %d snapshot(s), %d pool file(s)" % (len(drop), removed))


ROOT_LABELS = [
    ("BIC", P.BIC_ROOT), ("iQUAM", P.IQUAM_ROOT), ("landice p011", P.LANDICE_P011_ROOT),
    ("landice p01", P.LANDICE_P01_ROOT), ("coefficients", P.CSP_ROOT),
    ("L4 1km", P.L4_1KM_ROOT), ("L4 25km", P.L4_25KM_ROOT),
    ("hiresdt cache", P.HIRESDT_ROOT), ("MUR25 ice cache", P.MUR25_ICE_ROOT),
    ("L2P downloads", P.L2P_ROOT), ("run logs", P.NRT_LOG_DIR),
    ("mrva4com logs", P.MRVA_TMP_LOG_DIR), ("cyc4 code", P.CYC4_CODE_DIR),
]
# Not having these stops a capture; the rest only make it less complete.
CRITICAL_ROOTS = {"BIC", "iQUAM", "landice p011", "landice p01", "coefficients",
                  "L2P downloads", "run logs"}


# Captured for completeness, but neither MRVA here nor mrva4com reads them:
# p01's ice field and p011's land/ice grid (only the old v03 writer used it).
UNUSED_INPUTS = re.compile(r"^landice/(p01/\d{4}/Global_ice_|p011/\d{4}/landice_)")


def _group(rel):
    if UNUSED_INPUTS.match(rel):
        return "landice (unused)"
    head = rel.split("/")[0]
    if head == "bic":
        return "L2Plist" if "/L2Plist_" in rel else "BIC"
    if head == "landice":
        return "landice " + rel.split("/")[1]
    return {"iquam": "iQUAM", "csp_prior": "prior c06"}.get(head, head)


def cmd_check(args):
    """Read-only: can this host see everything a capture needs? Prints one
    line per thing checked and exits 1 when something essential is missing."""
    ops = Ops(args.fake_root, args.map)
    bad = []

    def line(ok, what, detail=""):
        mark = {True: "ok  ", False: "MISS", None: "warn"}[ok]
        print("  [%s] %-22s %s" % (mark, what, detail))

    print("host %s, reading prod paths%s" % (
        socket.gethostname(),
        " via " + ", ".join("%s=%s" % m for m in ops.maps) if ops.maps else " as-is"))
    print("\nroots")
    for label, root in ROOT_LABELS:
        real = ops(root)
        ok = os.path.isdir(real) and os.access(real, os.R_OK | os.X_OK)
        detail = real if real == os.path.realpath(real) else "%s -> %s" % (real, os.path.realpath(real))
        if not os.path.isdir(real):
            detail += "  (not there)"
        elif not ok:
            detail += "  (not readable by %s)" % os.environ.get("USER", "this user")
        crit = label in CRITICAL_ROOTS
        line(ok if ok or crit else None, label, detail)
        if not ok and crit:
            bad.append(label)

    print("\nrun")
    nrtlog = os.path.join(ops(P.NRT_LOG_DIR), "nrtMRVA.log")
    header = parse_run_header(read_from(nrtlog, max(0, file_size(nrtlog) - 200000)))
    if header:
        line(True, "nrtMRVA.log", "last run header: today=%s (mtime %s)"
             % (header[0], _iso(os.path.getmtime(nrtlog))))
    else:
        line(False, "nrtMRVA.log", "%s: no run header readable" % nrtlog)
        bad.append("nrtMRVA.log")
    procs = processes_matching("nrtMRVA.py")
    line(True if procs else None, "nrtMRVA.py process",
         "visible (running now)" if procs else
         "not visible: not running now, or this is not the prod host. watch "
         "then ends on the logs going quiet (--idle)")
    if args.run_date:
        run_date = _date(args.run_date)
    elif header:
        run_date = header[0]
    else:
        run_date = datetime.date.today()
    print("  checking the files of the run on %s" % run_date)

    for k in offsets(args.days):
        d = run_date + datetime.timedelta(days=k)
        mode = P.mode_for(run_date, d)
        print("\n%s  %s (%s)" % (P.tag(d), d, mode))
        groups = {}
        bics = {}
        for src, rel in day_input_files(d):
            if rel.endswith((".bic", ".bic.gz")):
                bics.setdefault(rel.split(".bic")[0], []).append(os.path.isfile(ops(src)))
                continue
            g = groups.setdefault(_group(rel), [0, 0, []])
            g[1] += 1
            if os.path.isfile(ops(src)):
                g[0] += 1
            else:
                g[2].append(src)
        have = sum(1 for v in bics.values() if any(v))
        line(have == len(bics), "BIC", "%d of %d (sensor, day) in the D+-2 windows"
             % (have, len(bics)))
        if have < len(bics):
            bad.append("%s BIC" % P.tag(d))
        for g, (n, total, missing) in sorted(groups.items()):
            if g == "prior c06":
                line(True if n else None, g, ("present" if n else "absent") +
                     ("" if n or mode == "rea" else ", normal for T-2/T-1 (NRT writes no c06)"))
                continue
            ok = n == total
            if g == "landice (unused)":
                line(True if ok else None, g, "%d of %d (not read by MRVA)" % (n, total))
                continue
            line(ok if ok or g != "L2Plist" else None, g, "%d of %d%s" % (
                n, total, "" if ok else "; first missing: " + missing[0]))
            if not ok and g.startswith(("landice", "iQUAM")):
                bad.append("%s %s" % (P.tag(d), g))
        # L2Plists name granules by their prod-host path: can this host open them?
        named = found = 0
        example = None
        for src, rel in day_input_files(d):
            if "/L2Plist_" not in rel:
                continue
            try:
                with open(ops(src)) as f:
                    paths = l2plist_paths(f.read())
            except OSError:
                continue
            for gp in paths:
                named += 1
                if os.path.isfile(ops(gp)):
                    found += 1
                elif example is None:
                    example = gp
        if named:
            line(found == named, "L2P granules", "%d of %d listed granules readable%s" % (
                found, named, "" if found == named else
                "; e.g. %s (purged after 30 days, or mounted elsewhere: --map)" % example))
            if found < named:
                bad.append("%s L2P granules" % P.tag(d))
        outs = day_output_files(ops, d, mode)
        l4 = [s for s, r in outs if r.startswith("l4/")]
        line(True if l4 else None, "outputs", "%d L4 file(s), %d coefficient/log file(s)" % (
            len(l4), sum(1 for s, r in outs if os.path.isfile(ops(s)) and not r.startswith("l4/"))))

    if args.snap_root:
        print("\nsnapshot root")
        sr = args.snap_root
        parent = sr if os.path.isdir(sr) else os.path.dirname(sr.rstrip("/"))
        ok = os.path.isdir(parent) and os.access(parent, os.W_OK)
        line(ok, "writable", sr)
        try:
            check_snap_root(ops, sr)
        except SystemExit as exc:
            line(False, "outside ops paths", str(exc))
            ok = False
        if ok:
            st = os.statvfs(parent)
            line(True, "free space", "%.0f GB" % (st.f_bavail * st.f_frsize / 1e9))
        else:
            bad.append("snapshot root")

    print("\n%s" % ("everything a capture needs is visible" if not bad else
                     "problems: " + ", ".join(bad)))
    return 1 if bad else 0


def cmd_prune(args):
    prune(args.snap_root, args.keep, args.dry_run)
    return 0


def _mapping(text):
    old, sep, new = text.partition("=")
    if not sep or not old.startswith("/") or not new.startswith("/"):
        raise argparse.ArgumentTypeError("expected /prod/prefix=/local/prefix, got %r" % text)
    return old, new


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--snap-root", required=True,
                       help="where snapshots go; must not be inside an ops path")
        p.add_argument("--days", default="-4:-1",
                       help="analysis days as offsets from the run date "
                            "(default -4:-1 = 1 REA + 3 NRT; up to -9:-1)")
        p.add_argument("--no-l2p", action="store_true",
                       help="skip copying L2P granules into the pool")
        p.add_argument("--map", action="append", default=[], type=_mapping,
                       metavar="PROD=LOCAL",
                       help="read prod path prefix PROD at LOCAL on this host "
                            "(repeatable), e.g. --map /nas2=/mnt/nas2")
        p.add_argument("--fake-root", help="read every ops path under this "
                                           "directory (tests, rehearsals)")
        p.add_argument("--dry-run", action="store_true",
                       help="log what would be copied; write nothing")
        p.add_argument("--keep", type=int, default=0,
                       help="after the run keep only the newest N snapshots")

    w = sub.add_parser("watch", help="wait for today's run and capture it")
    common(w)
    w.add_argument("--log-dir", default=P.NRT_LOG_DIR,
                   help="where nrtMRVA.log and MRVA_*.log appear")
    w.add_argument("--poll", type=float, default=10.0, help="seconds between polls")
    w.add_argument("--start-timeout", type=float, default=90,
                   help="minutes to wait for the run header before giving up")
    w.add_argument("--timeout", type=float, default=12, help="hours for the whole run")
    w.add_argument("--post-timeout", type=float, default=120,
                   help="minutes to wait for background csp2nc4a jobs")
    w.add_argument("--process", default="nrtMRVA.py",
                   help="program name of the run process")
    w.add_argument("--idle", type=float, default=15,
                   help="when the run's process is not visible from this host: "
                        "minutes of quiet logs, after the last wanted day "
                        "started, that mean the run is over (default %(default)s)")
    w.add_argument("--settle", type=float, default=3,
                   help="minutes a day's csp2nc log must be idle before its "
                        "outputs are copied")
    w.add_argument("--since", type=float, default=None,
                   help="epoch seconds; treat logs newer than this as this "
                        "run (default: now) and read nrtMRVA.log from the start")
    w.set_defaults(func=cmd_watch)

    o = sub.add_parser("once", help="capture a past run as it is on disk now")
    common(o)
    o.add_argument("--run-date", required=True, help="YYYY-MM-DD, the day nrtMRVA.py ran")
    o.set_defaults(func=cmd_once)

    c = sub.add_parser("check", help="read-only: report what this host can and "
                                     "cannot see; copies nothing")
    common(c)
    c.add_argument("--run-date", help="YYYY-MM-DD (default: the last run in nrtMRVA.log)")
    c.set_defaults(func=cmd_check, snap_root=None)
    for action in c._actions:
        if action.dest == "snap_root":
            action.required = False
    p = sub.add_parser("prune", help="apply --keep and drop unreferenced pool files")
    p.add_argument("--snap-root", required=True)
    p.add_argument("--keep", type=int, required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_prune)
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception:  # never break the cron line
        log("capture failed:\n" + traceback.format_exc())
        return 0


if __name__ == "__main__":
    sys.exit(main())
