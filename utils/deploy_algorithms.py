#!/usr/bin/env python3
"""Register the MUR application packages with MAAP.

Run this in a MAAP workspace, from a checkout of this repo:

    python utils/deploy_algorithms.py              # all four, current version
    python utils/deploy_algorithms.py --dry-run    # show what would happen
    python utils/deploy_algorithms.py --modules l2p
    python utils/deploy_algorithms.py --version 2.0.0    # redeploy an old one

WHY A SCRIPT
    deploy_algorithm_from_cwl_file() takes a file_path on the local
    filesystem, so deployment happens where the repo is checked out. That used
    to be a Python snippet printed by generate_cwl.sh for copy-pasting, which
    is a worse version of a file: it cannot be tested, cross-checked, or run
    twice the same way.

WHY IT NEVER GLOBS THE CWL DIRECTORY
    maap/cwl_workflows/ accumulates a file per version, and old ones are worth
    keeping -- they are how you redeploy 2.0.0 after 2.0.1 turns out to be
    wrong. That only stays safe if nothing can pick one up by accident, so the
    path is built from an explicit version and the file must exist at that
    exact name. `*.cwl` would deploy whatever happens to be lying there.

WHAT DEPLOYING DOES
    It registers an algorithm; it provisions nothing. Deploying the same name
    and version again ADDS a registration rather than replacing one, each with
    its own processID and its own frozen copy of the CWL -- so this reports
    every registration afterwards, and says which one the orchestrator will
    resolve.

    It is also ASYNCHRONOUS. MAAP answers 202 Accepted with a deploymentJobID
    and a link to a GitLab pipeline that does the real work; the process is not
    registered when that response arrives, and listing the algorithms straight
    away shows only the previous version. So this polls until each one appears,
    and says plainly if it does not. Treating 202 as done reported success for
    a deployment that had not happened yet.
"""
import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "utils"))

MODULES = ("iquam", "landice", "l2p", "mrva")     # cheapest first


def cwl_for(module: str, version: str) -> pathlib.Path:
    return REPO / "maap" / "cwl_workflows" / f"process_mur-{module}_{version}.cwl"


def registrations(maap, name: str):
    """Every (version, processID) currently registered under `name`."""
    resp = maap.list_algorithms()
    body = resp.json() if resp.content else {}
    # A bare list, not {"processes": [...]}: body.get would raise before the
    # isinstance default is ever consulted -- that default only applies when
    # body IS a dict lacking the key.
    procs = body if isinstance(body, list) else body.get("processes", [])
    return sorted(
        (str(p.get("version")), p.get("processID"))
        for p in procs if p.get("id") == name
    )


def wait_for_registration(maap, modules, version, *, timeout, poll_interval):
    """Block until every module is registered at `version`, or time runs out.

    Deployment is asynchronous: the 202 means a pipeline was queued. Polling
    the algorithm listing asks the only question that matters -- can a job be
    submitted against this version yet -- rather than inferring it from a
    deployment job's own status, which is a different thing that has been
    reported as finished before the process appeared.
    """
    import time

    if not modules:
        return set()

    print(f"\n==> Waiting for MAAP to register {len(modules)} process(es) "
          f"(up to {timeout:.0f}s)")
    deadline = time.monotonic() + timeout
    done = set()
    while True:
        for module in modules:
            if module in done:
                continue
            if any(v == version
                   for v, _ in registrations(maap, f"mur-{module}")):
                done.add(module)
                print(f"  registered  mur-{module} v{version}")
        if len(done) == len(modules):
            return done
        if time.monotonic() >= deadline:
            print(f"  timed out after {timeout:.0f}s")
            return done
        waiting = [m for m in modules if m not in done]
        print(f"  waiting on {', '.join(waiting)} ...")
        time.sleep(poll_interval)


def main(argv=None) -> int:
    from mur_maap.version import ALGORITHM_VERSION

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--modules", nargs="+", default=list(MODULES),
                        choices=list(MODULES))
    parser.add_argument("--version", default=ALGORITHM_VERSION,
                        help=f"default: {ALGORITHM_VERSION}, from mur_maap/version.py")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-check", action="store_true",
                        help="skip the CWL/config cross-check (not advised)")
    parser.add_argument("--no-wait", action="store_true",
                        help="submit the deployments and exit without waiting "
                             "for MAAP to finish registering them")
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="seconds to wait for registration (default: %(default)s)")
    parser.add_argument("--poll-interval", type=float, default=15.0,
                        help="seconds between checks (default: %(default)s)")
    args = parser.parse_args(argv)

    version = args.version
    if version != ALGORITHM_VERSION:
        print(f"NOTE: deploying {version}, but this checkout builds "
              f"{ALGORITHM_VERSION}. Jobs run whatever run_mur_maap.py "
              f"resolves, which is {ALGORITHM_VERSION} unless the config "
              f"overrides it.\n")

    # Every file must exist before anything is registered. A partial deploy
    # leaves some modules on the new version and some on the old, which is a
    # worse state than not having started.
    missing = [m for m in args.modules if not cwl_for(m, version).is_file()]
    if missing:
        print(f"ERROR: no CWL at {version} for: {', '.join(missing)}")
        print(f"       Expected e.g. {cwl_for(missing[0], version)}")
        print(f"       Generate them first:  ./utils/generate_cwl.sh")
        return 1

    # The cross-check reads algorithm_config.yml, which describes the CURRENT
    # version. An older CWL cannot be checked against it -- the config moved
    # on, and that is exactly why the old file was kept. Checking anyway would
    # report every module as MISSING and block the rollback.
    if args.skip_check:
        pass
    elif version != ALGORITHM_VERSION:
        print(f"==> Skipping the config cross-check: it compares against "
              f"algorithm_config.yml,\n    which is at {ALGORITHM_VERSION}. "
              f"A {version} CWL predates it. Deploying the file as committed.\n")
    else:
        import check_cwl_against_config as check
        print("==> Cross-checking each CWL against its config")
        if check.main([str(REPO), *args.modules]) != 0:
            print("\nERROR: refusing to deploy a CWL that does not match its "
                  "config.\n       Fix it, or pass --skip-check if you are "
                  "certain.")
            return 1
        print()

    print(f"==> Deploying at {version}")
    for module in args.modules:
        print(f"  mur-{module}  <- {cwl_for(module, version).name}")
    if args.dry_run:
        print("\nDry run: nothing was registered.")
        return 0

    try:
        from maap.maap import MAAP
    except ImportError:
        print("\nERROR: maap-py is not installed. This script must run in a "
              "MAAP workspace.\n       pip install maap-py")
        return 1

    maap = MAAP()
    print()
    pipelines = {}
    submitted = []
    for module in args.modules:
        path = cwl_for(module, version)
        resp = maap.deploy_algorithm_from_cwl_file(file_path=str(path))
        try:
            body = resp.json()
        except ValueError:
            body = {}

        # 202 Accepted: MAAP has queued a pipeline, not registered anything.
        job_id = body.get("deploymentJobID") if isinstance(body, dict) else None
        status = body.get("status") if isinstance(body, dict) else None
        if 200 <= resp.status_code < 300:
            submitted.append(module)
            detail = f"deploymentJobID {job_id}" if job_id else (status or "accepted")
            print(f"  mur-{module}: HTTP {resp.status_code}  {detail}")
            if isinstance(body, dict):
                link = (body.get("processPipelineLink") or {}).get("href")
                if link:
                    pipelines[module] = link
        else:
            text = body if body else resp.text[:200]
            print(f"  mur-{module}: HTTP {resp.status_code}  {text}")

    rejected = [m for m in args.modules if m not in submitted]
    if rejected:
        print(f"\nMAAP refused {len(rejected)}: {', '.join(rejected)}")

    if args.no_wait:
        print("\n--no-wait: deployments are queued but not yet registered.")
        for module, link in pipelines.items():
            print(f"  mur-{module}: {link}")
        return 1 if rejected else 0

    registered = wait_for_registration(
        maap, submitted, version,
        timeout=args.timeout, poll_interval=args.poll_interval)

    print("\n==> Registrations now visible to MAAP")
    still_missing = []
    for module in args.modules:
        name = f"mur-{module}"
        rows = registrations(maap, name)
        at_version = [pid for v, pid in rows if v == version]
        if not at_version:
            still_missing.append(module)
        resolves = max(at_version) if at_version else None
        if not rows:
            print(f"  {name}: no registrations at all")
            continue
        for v, pid in rows:
            mark = " <- resolves here" if pid == resolves else ""
            print(f"  {name}  v{v}  processID {pid}{mark}")
        if len(at_version) > 1:
            print(f"      NOTE: {len(at_version)} registrations at v{version}. "
                  f"Each holds its own copy of the CWL; run_mur_maap.py takes "
                  f"the highest processID.")

    if still_missing or rejected:
        print(f"\nNOT registered at {version}: "
              f"{', '.join(sorted(set(still_missing) | set(rejected)))}")
        for module in sorted(set(still_missing)):
            if module in pipelines:
                print(f"  mur-{module} pipeline: {pipelines[module]}")
        print("\nA deployment pipeline can still be running, or it can have "
              "failed.\nThe pipeline link above says which. Do not submit jobs "
              "until this is clean --\nrun_mur_maap.py would resolve the "
              "PREVIOUS version and run it silently.")
        return 1

    print(f"\nAll {len(args.modules)} registered at {version}. Run one job "
          f"before trusting the rest --\nthe first job log prints the image "
          f"build:\n    MUR image build: <sha>-<timestamp>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
