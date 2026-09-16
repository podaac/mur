#!/usr/bin/env python3
"""Stage the MUR static-resources tree into a MAAP workspace S3 bucket.

WHY THIS IS PYTHON AND NOT `aws s3 sync`
  The upload is ~142 GiB across 377 objects and will outlive any single set of
  STS credentials. `maap.aws.workspace_bucket_credentials()` returns temporary
  keys with an `expires_at`; `aws s3 sync` reads credentials once at start and
  dies with ExpiredToken partway through. botocore's RefreshableCredentials
  re-mints them transparently before signing each request, which makes expiry a
  non-event and needs no `aws` binary on the source host.

  The verifier also has to `import` the pipeline's own resolvers, so that "did
  the upload land correctly" is answered by the same code the pipeline uses
  rather than a second transcription of the layout.

WHERE TO RUN IT
  On the production host, streaming straight from the NAS to S3 -- that moves
  the bytes once and needs no scratch disk. Going via a laptop moves 284 GiB
  and needs 142 GiB free. Do NOT tar first: bundle_prod_static.sh produces a
  single 142 GiB tarball that then has to be untarred somewhere to become
  objects again.

  Pre-flight (a 403 means "reachable, anonymous denied" -- that is success):
    curl -sS -o /dev/null -w '%{http_code}\\n' https://<bucket>.s3.<region>.amazonaws.com/
    curl -sS -o /dev/null -w '%{http_code}\\n' https://api.maap-project.org/

TYPICAL SEQUENCE
    # see the plan, resolve credentials, upload nothing
    python utils/upload_static_resources.py --from-prod-layout --dry-run --include-optional

    # ~1.5 GiB, minutes -- unblocks all landice testing
    python utils/upload_static_resources.py --from-prod-layout --include-optional \\
        --no-seasonal --verify

    # ~141 GiB, hours; survives token expiry; resumable
    nohup python utils/upload_static_resources.py --from-prod-layout --seasonal-only \\
        --ledger ~/mur_static_ledger.jsonl > ~/mur_upload.log 2>&1 &

    # from anywhere, afterwards
    python utils/upload_static_resources.py --verify-only --include-optional
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import pathlib
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import static_resources_layout as layout  # noqa: E402

DEFAULT_SUBPREFIX = "mur/static-resources"
REFRESH_MARGIN_SECONDS = 900  # re-mint with 15 min left, matching botocore's advisory refresh


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------

def _maap_client():
    from maap.maap import MAAP  # imported lazily: not needed for --help/--dry-run parsing
    return MAAP()


def _credentials_payload(maap) -> Dict:
    """One call to MAAP, normalized into botocore's metadata shape."""
    resp = maap.aws.workspace_bucket_credentials()
    creds = resp["credentials"]
    return {
        "access_key": creds["aws_access_key_id"],
        "secret_key": creds["aws_secret_access_key"],
        "token": creds["aws_session_token"],
        "expiry_time": creds.get("expires_at") or creds.get("expiration"),
    }, resp


def workspace_session(maap):
    """A boto3 Session whose credentials refresh themselves.

    botocore checks expiry before signing every request, so a refresh lands
    between multipart parts and is invisible to an in-flight upload.
    """
    import boto3
    from botocore.credentials import RefreshableCredentials
    from botocore.session import get_session

    def fetch():
        payload, _ = _credentials_payload(maap)
        return payload

    initial = fetch()
    session = get_session()
    session._credentials = RefreshableCredentials.create_from_metadata(
        metadata=initial,
        refresh_using=fetch,
        method="maap-workspace",
    )
    return boto3.Session(botocore_session=session)


def default_destination(maap) -> str:
    """The workspace root, discovered rather than hardcoded.

    authorized_s3_paths[0] is documented as always being the workspace path.
    """
    _, resp = _credentials_payload(maap)
    workspace = resp["authorized_s3_paths"][0]
    return f"{workspace['uri'].rstrip('/')}/{DEFAULT_SUBPREFIX}"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def split_s3_uri(uri: str) -> Tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"destination must be an s3:// URI, got {uri!r}")
    bucket, _, prefix = uri[len("s3://"):].partition("/")
    return bucket, prefix.strip("/")


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


def sha256_of(path: pathlib.Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


class Ledger:
    """Append-only record of what landed, fsync'd per line so a kill -9 loses
    at most the file currently in flight."""

    def __init__(self, path: Optional[pathlib.Path]):
        self.path = path
        self.done: Dict[str, Dict] = {}
        if path and path.exists():
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # a torn final line from a hard kill
                    self.done[rec["relative_path"]] = rec

    def record(self, rec: Dict) -> None:
        self.done[rec["relative_path"]] = rec
        if not self.path:
            return
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())


# --------------------------------------------------------------------------
# upload
# --------------------------------------------------------------------------

def build_plan(args) -> List[layout.Entry]:
    kwargs = dict(
        include_optional=args.include_optional,
        include_seasonal=not args.no_seasonal,
    )
    if args.source_root:
        kwargs["source_root"] = args.source_root

    entries = list(layout.iter_entries(**kwargs))

    if args.seasonal_only:
        entries = [e for e in entries if e.group == "seasonal"]
    if args.only:
        entries = [e for e in entries if fnmatch.fnmatch(e.relative_path, args.only)]
    if args.limit:
        entries = entries[:args.limit]
    return entries


def print_plan(entries: Iterable[layout.Entry], dest: str, plan_json=None) -> int:
    entries = list(entries)
    missing = [e for e in entries if not e.exists]
    by_group: Dict[str, List[layout.Entry]] = {}
    total = 0

    print(f"Destination  : {dest}\n")
    for e in entries:
        size = e.source.stat().st_size if e.exists else 0
        total += size
        by_group.setdefault(e.group, []).append(e)
        flag = "" if e.exists else "   *** MISSING ***"
        print(f"  {human(size):>12}  {e.source}  ->  {e.relative_path}{flag}")

    print(f"\nTotals: {len(entries)} objects, {human(total)}")
    for group in sorted(by_group):
        group_entries = by_group[group]
        group_size = sum(e.source.stat().st_size for e in group_entries if e.exists)
        print(f"  {group:<10}: {len(group_entries):>4} objects, {human(group_size)}")

    if missing:
        print(f"\nMISSING ({len(missing)}):")
        for e in missing:
            required = "required" if e.required else "optional"
            print(f"  {e.source}  ({required})")

    if plan_json:
        pathlib.Path(plan_json).write_text(json.dumps([
            {"relative_path": e.relative_path, "source": str(e.source),
             "required": e.required, "group": e.group, "exists": e.exists,
             "size": e.source.stat().st_size if e.exists else None}
            for e in entries
        ], indent=2))
        print(f"\nPlan written to {plan_json}")

    return sum(1 for e in missing if e.required)


def upload(entries, s3, bucket, prefix, args) -> int:
    from boto3.s3.transfer import TransferConfig
    from botocore.exceptions import ClientError

    transfer = TransferConfig(
        multipart_threshold=args.part_size_mb * 1024 * 1024,
        multipart_chunksize=args.part_size_mb * 1024 * 1024,
        max_concurrency=args.concurrency,
        use_threads=True,
    )
    ledger = Ledger(pathlib.Path(args.ledger) if args.ledger else None)

    todo = [e for e in entries if e.exists]
    total_bytes = sum(e.source.stat().st_size for e in todo)
    uploaded = skipped = failed = 0
    moved = 0
    started = time.time()

    for i, entry in enumerate(todo, 1):
        size = entry.source.stat().st_size
        key = f"{prefix}/{entry.relative_path}" if prefix else entry.relative_path

        prior = ledger.done.get(entry.relative_path)
        if prior and prior.get("size") == size and not args.no_trust_ledger:
            skipped += 1
            continue
        if args.no_trust_ledger or not prior:
            try:
                head = s3.head_object(Bucket=bucket, Key=key)
                if head["ContentLength"] == size:
                    skipped += 1
                    ledger.record({
                        "relative_path": entry.relative_path, "key": key,
                        "size": size, "sha256": None,
                        "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "note": "already present",
                    })
                    continue
            except ClientError:
                pass  # absent or inaccessible -> upload it

        extra = {}
        digest = None
        if args.checksum == "sha256":
            digest = sha256_of(entry.source)
            extra["Metadata"] = {"sha256": digest}

        t0 = time.time()
        try:
            s3.upload_file(str(entry.source), bucket, key,
                           ExtraArgs=extra or None, Config=transfer)
        except Exception as exc:                      # noqa: BLE001 -- report and continue
            failed += 1
            print(f"[{i}/{len(todo)}] FAILED {entry.relative_path}: {exc}", file=sys.stderr)
            continue

        elapsed = max(time.time() - t0, 1e-6)
        moved += size
        uploaded += 1
        ledger.record({
            "relative_path": entry.relative_path, "key": key, "size": size,
            "sha256": digest,
            "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

        pct = 100.0 * moved / total_bytes if total_bytes else 100.0
        rate = size / elapsed / (1024 * 1024)
        print(f"[{i}/{len(todo)}] {entry.relative_path}  {human(size)}  "
              f"{elapsed:,.1f}s  {rate:,.1f} MB/s  ({pct:.1f}% of bytes)")

    wall = time.time() - started
    print(f"\nuploaded={uploaded} skipped={skipped} failed={failed}  "
          f"moved={human(moved)} in {wall/60:,.1f} min")
    if failed:
        print("Re-run the same command to retry only what failed "
              "(the ledger skips what already landed).", file=sys.stderr)
    return 1 if failed else 0


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify(entries, s3, bucket, prefix, dest, args) -> int:
    """Three layers, cheapest first. All must pass."""
    from botocore.exceptions import ClientError
    from run_mur_maap import resolve_landice_static_hrefs, resolve_mrva_static_hrefs

    problems = 0

    # 1. Inventory -- what is actually in the bucket vs what should be.
    print("[1/3] Inventory")
    listed = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/" if prefix else ""):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix) + 1:] if prefix else obj["Key"]
            listed[rel] = obj["Size"]

    expected = {e.relative_path: e for e in entries}
    missing = sorted(set(expected) - set(listed))
    extra = sorted(set(listed) - set(expected))
    wrong_size = [
        rel for rel in sorted(set(expected) & set(listed))
        if expected[rel].exists and listed[rel] != expected[rel].source.stat().st_size
    ]

    print(f"      {len(listed)} objects in bucket, {len(expected)} expected")
    for rel in missing:
        print(f"      MISSING  {rel}")
    for rel in wrong_size:
        print(f"      SIZE     {rel}: bucket={listed[rel]} "
              f"local={expected[rel].source.stat().st_size}")
    for rel in extra:
        print(f"      extra    {rel}  (not in the layout; harmless)")
    problems += len(missing) + len(wrong_size)

    # 2. Contract resolution -- the layer that actually matters. Exercises the
    #    orchestrator's own resolvers against the real bucket, for all 366 days
    #    (which also covers seasonal_relative_path's 366 -> 365 fold).
    print("[2/3] Contract resolution (run_mur_maap's own resolvers)")
    hrefs = dict(resolve_landice_static_hrefs(dest))
    for doy in range(1, 367):
        for name, href in resolve_mrva_static_hrefs(dest, doy).items():
            if name == "mur25_grid" and not args.include_optional:
                continue
            hrefs[f"{name}_{doy}"] = href

    checked = set()
    unresolved = []
    for href in hrefs.values():
        if href in checked:
            continue
        checked.add(href)
        _, key = split_s3_uri(href)
        try:
            s3.head_object(Bucket=bucket, Key=key)
        except ClientError:
            unresolved.append(href)

    print(f"      {len(checked)} distinct hrefs resolved, {len(unresolved)} unresolvable")
    for href in unresolved:
        print(f"      UNRESOLVED  {href}")
    problems += len(unresolved)

    # 3. Integrity -- opt-in, full local read pass.
    if args.checksum == "sha256":
        print("[3/3] Integrity (sha256)")
        mismatches = 0
        for entry in entries:
            if not entry.exists:
                continue
            key = f"{prefix}/{entry.relative_path}" if prefix else entry.relative_path
            try:
                head = s3.head_object(Bucket=bucket, Key=key)
            except ClientError:
                continue  # already reported by layer 1
            remote = (head.get("Metadata") or {}).get("sha256")
            if remote and remote != sha256_of(entry.source):
                print(f"      CHECKSUM {entry.relative_path}")
                mismatches += 1
        print(f"      {mismatches} mismatches")
        problems += mismatches
    else:
        print("[3/3] Integrity  skipped (pass --checksum sha256 to enable)")

    print("\nVERIFY: " + ("OK" if problems == 0 else f"{problems} problem(s)"))
    return 1 if problems else 0


# --------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Stage MUR static resources into a MAAP workspace S3 bucket.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("TYPICAL SEQUENCE")[-1],
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--source-root", type=pathlib.Path,
                     help="A static-resources/-shaped directory tree.")
    src.add_argument("--from-prod-layout", action="store_true",
                     help="The scattered production tree, via GRIDS_DIR/ICE_DIR/"
                          "SEASONAL_DIR/POLARCAP_FILE (same contract as "
                          "bundle_prod_static.sh, legacy p011 fallback included).")

    p.add_argument("--dest", help="s3://bucket/prefix root. Default: the workspace "
                                  "bucket from workspace_bucket_credentials().")
    p.add_argument("--include-optional", action="store_true",
                   help="Also stage the four OSI-SAF generator inputs (~9.6 MB).")
    sel = p.add_mutually_exclusive_group()
    sel.add_argument("--no-seasonal", action="store_true",
                     help="Skip the 365 seasonal files (~141 GB). Run this first.")
    sel.add_argument("--seasonal-only", action="store_true",
                     help="Only the seasonal files.")
    p.add_argument("--only", metavar="GLOB",
                   help="Filter by relative path, e.g. 'seasonal/mur_1??.nc'.")
    p.add_argument("--limit", type=int, help="Stage at most N objects (testing).")

    p.add_argument("--dry-run", action="store_true",
                   help="Resolve credentials, print the full plan, upload nothing.")
    p.add_argument("--plan-json", help="Also write the plan to this JSON file.")
    p.add_argument("--ledger", default="static_upload_ledger.jsonl",
                   help="Append-only record of what landed (default: %(default)s).")
    p.add_argument("--no-trust-ledger", action="store_true",
                   help="HEAD every object instead of trusting the ledger.")
    p.add_argument("--checksum", choices=("none", "sha256"), default="none",
                   help="sha256 costs a full extra local read pass (default: none).")
    p.add_argument("--verify", action="store_true", help="Verify after uploading.")
    p.add_argument("--verify-only", action="store_true", help="Verify and exit.")

    p.add_argument("--concurrency", type=int, default=8,
                   help="Parts in flight per file (default: %(default)s).")
    p.add_argument("--part-size-mb", type=int, default=64,
                   help="Multipart chunk size in MiB (default: %(default)s).")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    entries = build_plan(args)

    if args.dry_run:
        maap = None
        dest = args.dest
        if not dest:
            try:
                maap = _maap_client()
                dest = default_destination(maap)
                print("Credentials  : OK")
            except Exception as exc:                  # noqa: BLE001
                print(f"Credentials  : UNAVAILABLE ({exc})")
                dest = "s3://<workspace-bucket>/<user>/" + DEFAULT_SUBPREFIX
        missing_required = print_plan(entries, dest, args.plan_json)
        if missing_required:
            print(f"\n{missing_required} REQUIRED file(s) missing at the source.",
                  file=sys.stderr)
            return 1
        print("\nDry run: nothing uploaded.")
        return 0

    maap = _maap_client()
    dest = args.dest or default_destination(maap)
    bucket, prefix = split_s3_uri(dest)
    s3 = workspace_session(maap).client("s3")
    print(f"Destination  : {dest}")

    if args.verify_only:
        return verify(entries, s3, bucket, prefix, dest, args)

    rc = upload(entries, s3, bucket, prefix, args)
    if args.verify:
        rc = verify(entries, s3, bucket, prefix, dest, args) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
