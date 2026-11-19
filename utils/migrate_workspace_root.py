#!/usr/bin/env python3
"""Copy the pipeline's data tree from one workspace root to another.

    python utils/migrate_workspace_root.py                  # report, copy nothing
    python utils/migrate_workspace_root.py --copy           # copy what is missing
    python utils/migrate_workspace_root.py --copy --only 'mur/l4/*'
    python utils/migrate_workspace_root.py --verify         # compare both sides

Run it in a MAAP workspace: it needs credentials for both buckets.

WHAT IT MOVES
    Everything under <source>/mur/ -- cached BICs, iQuam, landice,
    coefficients, promoted L4s, manifests, sidecar STAC items, static
    resources -- to the same keys under <dest>/mur/. The source defaults to
    this account's personal workspace and the destination to the team (org)
    bucket MAAP authorizes it for -- found by searching for "mur" in the
    name, see --match -- so with no arguments it plans the move
    maap.workspace_root is about to make.

    Copies are server-side: no bytes pass through this machine. Objects over
    5 GB are copied in parts, which a plain CopyObject cannot do.

WHAT IT REWRITES
    JSON objects (manifests, sidecar STAC items, run state) embed absolute
    s3:// hrefs. Any that point under <source>/mur/ are repointed at
    <dest>/mur/ on the way across, so a copied STAC item links to the copied
    granule. Hrefs to anywhere else are left alone -- in particular
    <source>/dps_output/, which does not move.

WHAT IT DOES NOT TOUCH
    - The source. Nothing is deleted; remove the old tree yourself once the
      pipeline has run from the new root.
    - dps_output/. DPS stages every job's output in the submitting user's
      personal workspace whatever the root is, and the items MAAP published
      to dps-stac point there. They cannot be edited (the API is read-only),
      so moving those files would break every published link for good.

RESUMABLE
    An object already at the destination is skipped: a data file when the
    size matches, a JSON file when the destination copy is at least as new
    as the source. Re-run after an interruption and it carries on.
"""
import argparse
import concurrent.futures
import fnmatch
import pathlib
import sys
from typing import Dict, Iterable, List, Optional, Tuple

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mur_maap import paths                                     # noqa: E402
from mur_maap.workspace import WorkspaceBucket, split_s3_uri   # noqa: E402

TREE = "mur"

# Rewriting means reading the object into memory. Every JSON the pipeline
# writes is a few kilobytes; anything far larger is not one of ours and is
# copied as opaque data instead.
MAX_REWRITE_BYTES = 16 * 2**20

COPY, REWRITE, SKIP = "copy", "rewrite", "skip"


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TiB"


def join(root_key: str, rel: str) -> str:
    """A key under a root prefix that may be empty (a bucket root)."""
    root_key = root_key.strip("/")
    return f"{root_key}/{rel}" if root_key else rel


def rewrite_text(text: str, source_root: str, dest_root: str,
                 tree: str = TREE) -> str:
    """Repoint hrefs under <source_root>/<tree>/ at <dest_root>/<tree>/.

    Anchored on the tree and its trailing slash, so <source_root>/dps_output/
    and a sibling such as <source_root>/mur-old/ are left as they are.
    """
    old = f"{source_root.rstrip('/')}/{tree}/"
    new = f"{dest_root.rstrip('/')}/{tree}/"
    return text.replace(old, new)


def is_json(rel: str, size: int) -> bool:
    return rel.endswith(".json") and size <= MAX_REWRITE_BYTES


def plan(source: Dict[str, Dict], dest: Dict[str, Dict],
         only: Optional[str] = None) -> List[Tuple[str, str, int]]:
    """(action, relative key, size) for every source object, sorted by key.

    `source` and `dest` map a key relative to the root to its listing entry
    (Size, LastModified).
    """
    actions = []
    for rel in sorted(source):
        if only and not fnmatch.fnmatch(rel, only):
            continue
        src, dst = source[rel], dest.get(rel)
        size = src["Size"]
        if is_json(rel, size):
            fresh = dst is not None and dst["LastModified"] >= src["LastModified"]
            actions.append((SKIP if fresh else REWRITE, rel, size))
        else:
            same = dst is not None and dst["Size"] == size
            actions.append((SKIP if same else COPY, rel, size))
    return actions


def listing(s3, bucket: str, root_key: str, tree: str = TREE) -> Dict[str, Dict]:
    """Every object under <root>/<tree>/, keyed relative to the root."""
    prefix = join(root_key, tree) + "/"
    strip = len(prefix) - len(tree) - 1
    found = {}
    for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            found[obj["Key"][strip:]] = obj
    return found


def summarize(actions: Iterable[Tuple[str, str, int]]) -> Dict[str, Tuple[int, int]]:
    totals = {COPY: [0, 0], REWRITE: [0, 0], SKIP: [0, 0]}
    for action, _, size in actions:
        totals[action][0] += 1
        totals[action][1] += size
    return {k: tuple(v) for k, v in totals.items()}


def by_area(actions: Iterable[Tuple[str, str, int]]) -> Dict[str, List[int]]:
    """Pending objects and bytes per top-level area: mur/l4, mur/bic, ..."""
    areas: Dict[str, List[int]] = {}
    for action, rel, size in actions:
        if action == SKIP:
            continue
        area = "/".join(rel.split("/")[:2])
        entry = areas.setdefault(area, [0, 0])
        entry[0] += 1
        entry[1] += size
    return areas


def transfer(s3, action: str, rel: str, src: Tuple[str, str],
             dst: Tuple[str, str], roots: Tuple[str, str]) -> None:
    """Move one object. `src` and `dst` are (bucket, root key)."""
    src_bucket, src_key = src[0], join(src[1], rel)
    dst_bucket, dst_key = dst[0], join(dst[1], rel)
    if action == REWRITE:
        body = s3.get_object(Bucket=src_bucket, Key=src_key)["Body"].read()
        try:
            body = rewrite_text(body.decode("utf-8"), *roots).encode("utf-8")
        except UnicodeDecodeError:
            pass                          # not text after all: copy it verbatim
        s3.put_object(Bucket=dst_bucket, Key=dst_key, Body=body,
                      ContentType="application/json")
    else:
        # The managed copy, not copy_object: it switches to a multipart copy
        # above its threshold, and CopyObject alone refuses anything over 5 GB.
        s3.copy({"Bucket": src_bucket, "Key": src_key}, dst_bucket, dst_key)


def verify(source: Dict[str, Dict], dest: Dict[str, Dict],
           only: Optional[str] = None) -> List[str]:
    """What is wrong at the destination, one line per object; empty if nothing."""
    problems = []
    for rel in sorted(source):
        if only and not fnmatch.fnmatch(rel, only):
            continue
        src, dst = source[rel], dest.get(rel)
        if dst is None:
            problems.append(f"missing    {rel}")
        elif not is_json(rel, src["Size"]) and dst["Size"] != src["Size"]:
            problems.append(f"size       {rel}  source {src['Size']}  "
                            f"dest {dst['Size']}")
    return problems


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", help="s3:// root to copy from. Default: this "
                   "account's personal workspace.")
    p.add_argument("--dest", help="s3:// root to copy to. Default: the team "
                   "(org) bucket MAAP authorizes this account for whose name "
                   "contains --match.")
    p.add_argument("--match", default=paths.TEAM_BUCKET_MATCH,
                   help="Text to look for in the team bucket's name "
                        "(default: %(default)s).")
    p.add_argument("--only", metavar="GLOB",
                   help="Only keys matching this glob, relative to the root "
                        "(e.g. 'mur/l4/*', 'mur/stac/*').")
    p.add_argument("--copy", action="store_true",
                   help="Copy. Without it this only reports.")
    p.add_argument("--verify", action="store_true",
                   help="Compare the two trees and exit non-zero on a difference.")
    p.add_argument("--concurrency", type=int, default=16)
    return p.parse_args(argv)


def resolve_roots(args, workspace) -> Tuple[str, str]:
    source = args.source or workspace.path().uri
    dest = args.dest
    if not dest:
        org = workspace.org_path(args.match)
        if org is None:
            raise SystemExit(
                f"MAAP authorizes this account for no team (org) bucket "
                f"matching {args.match!r}; pass --dest.")
        dest = org.uri
    source, dest = source.rstrip("/"), dest.rstrip("/")
    if source == dest:
        raise SystemExit(f"source and destination are both {source}")
    return source, dest


def main(argv=None, *, workspace=None) -> int:
    args = parse_args(argv)
    if workspace is None:
        from maap.maap import MAAP
        workspace = WorkspaceBucket(MAAP())
    source_root, dest_root = resolve_roots(args, workspace)
    src, dst = split_s3_uri(source_root), split_s3_uri(dest_root)
    s3 = workspace.s3()

    print(f"source  {source_root}/{TREE}/")
    print(f"dest    {dest_root}/{TREE}/")
    source = listing(s3, *src)
    dest = listing(s3, *dst)
    print(f"        {len(source)} object(s) at the source, "
          f"{len(dest)} at the destination\n")

    if args.verify:
        problems = verify(source, dest, args.only)
        for line in problems:
            print(line)
        print(f"\n{len(problems)} difference(s)." if problems
              else "Destination has every source object at the same size.")
        return 1 if problems else 0

    actions = plan(source, dest, args.only)
    totals = summarize(actions)
    for area, (count, size) in sorted(by_area(actions).items()):
        print(f"  {area:28} {count:>8} object(s)  {human(size):>12}")
    print(f"\n  to copy      {totals[COPY][0]:>8}  {human(totals[COPY][1]):>12}")
    print(f"  to rewrite   {totals[REWRITE][0]:>8}  {human(totals[REWRITE][1]):>12}"
          "   (JSON, hrefs repointed)")
    print(f"  already done {totals[SKIP][0]:>8}  {human(totals[SKIP][1]):>12}")

    pending = [a for a in actions if a[0] != SKIP]
    if not pending:
        print("\nNothing to do.")
        return 0
    if not args.copy:
        print("\nDry run. Add --copy to copy these objects.")
        return 0

    failed, done, done_bytes = [], 0, 0
    total_bytes = sum(size for _, _, size in pending)
    with concurrent.futures.ThreadPoolExecutor(args.concurrency) as pool:
        futures = {
            pool.submit(transfer, s3, action, rel, src, dst,
                        (source_root, dest_root)): (rel, size)
            for action, rel, size in pending
        }
        for future in concurrent.futures.as_completed(futures):
            rel, size = futures[future]
            try:
                future.result()
            except Exception as exc:              # report all, then fail
                failed.append((rel, exc))
                continue
            done += 1
            done_bytes += size
            if done % 200 == 0 or done == len(pending):
                print(f"  {done}/{len(pending)} object(s)  "
                      f"{human(done_bytes)} of {human(total_bytes)}", flush=True)

    for rel, exc in failed:
        print(f"FAILED  {rel}: {exc}", file=sys.stderr)
    if failed:
        print(f"\n{len(failed)} object(s) failed; re-run to retry them.",
              file=sys.stderr)
        return 1
    print("\nDone. Run again with --verify to compare the two trees.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
