#!/usr/bin/env python3
"""Dump everything MAAP will say about a job id, raw.

    python utils/job_probe.py 2898989c-605b-48e8-86c8-49ff0d5b37c0

WHY THIS EXISTS
    A run died on

      MAAP returned HTTP 500 asking for the result of job 2898989c-...:
      Failed to get job result of job with id: 2898989c-...
      'NoneType' object has no attribute 'get'.

    after that job had polled clean to a terminal status -- and the id does
    not appear under "View My Jobs". Those three facts do not fit together,
    and no amount of reading our own code settles it: the answer is in what
    the API returns for that id, unparsed.

    So this prints the HTTP code and the verbatim body of get_job_status and
    get_job_result, and says whether list_jobs knows the id at all. It parses
    nothing and normalizes nothing -- our parsing is exactly what is in
    question.
"""
import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def dump(label, resp):
    code = getattr(resp, "status_code", "?")
    print(f"\n  {label}: HTTP {code}")
    try:
        body = resp.json() if resp.content else {}
        print("    " + json.dumps(body, indent=2, default=str
                                  ).replace("\n", "\n    "))
    except Exception:                                          # noqa: BLE001
        raw = getattr(resp, "text", "") or repr(getattr(resp, "content", b""))
        print(f"    (not JSON) {raw[:2000]}")


def all_jobs(maap):
    resp = maap.list_jobs()
    body = resp.json() if resp.content else {}
    rows = body if isinstance(body, list) else (
        body.get("jobs") or body.get("results") or [])
    return [r for r in rows if isinstance(r, dict)]


def job_id_of(row):
    return next((row[k] for k in ("jobID", "jobId", "job_id", "id")
                 if row.get(k)), None)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job_ids", nargs="+")
    ap.add_argument("--no-listing", action="store_true",
                    help="skip the list_jobs cross-check (it can be slow)")
    args = ap.parse_args(argv)

    from mur_maap.client import MaapPyClient
    from mur_maap.version import ALGORITHM_VERSION
    client = MaapPyClient(queue="__read_only__", version=ALGORITHM_VERSION)
    maap = client.maap

    listing = None
    if not args.no_listing:
        try:
            listing = all_jobs(maap)
            print(f"list_jobs returned {len(listing)} job(s)")
        except Exception as exc:                               # noqa: BLE001
            print(f"list_jobs failed: {exc}")

    for job_id in args.job_ids:
        print(f"\n{'=' * 72}\n{job_id}\n{'=' * 72}")

        if listing is not None:
            row = next((r for r in listing if job_id_of(r) == job_id), None)
            if row is None:
                print("  list_jobs: NOT PRESENT -- MAAP does not list this id "
                      "among your jobs. A deduped submission looks exactly "
                      "like this.")
            else:
                print("  list_jobs: present")
                print("    " + json.dumps(row, indent=2, default=str
                                          ).replace("\n", "\n    "))

        for label, call in (("get_job_status", maap.get_job_status),
                            ("get_job_result", maap.get_job_result)):
            try:
                dump(label, call(job_id))
            except Exception as exc:                           # noqa: BLE001
                print(f"\n  {label}: raised {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
