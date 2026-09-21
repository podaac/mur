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
    failed = []
    for module in args.modules:
        path = cwl_for(module, version)
        resp = maap.deploy_algorithm_from_cwl_file(file_path=str(path))
        ok = 200 <= resp.status_code < 300
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:200]
        print(f"  mur-{module}: HTTP {resp.status_code} {body}")
        if not ok:
            failed.append(module)

    print("\n==> Registrations now visible to MAAP")
    for module in args.modules:
        name = f"mur-{module}"
        rows = registrations(maap, name)
        if not rows:
            print(f"  {name}: none -- the deploy did not take effect")
            failed.append(module)
            continue
        at_version = [pid for v, pid in rows if v == version]
        for v, pid in rows:
            mark = " <- resolves here" if (v == version
                                           and pid == max(at_version)) else ""
            print(f"  {name}  v{v}  processID {pid}{mark}")
        if len(at_version) > 1:
            print(f"      NOTE: {len(at_version)} registrations at v{version}. "
                  f"Each holds its own copy of the CWL; run_mur_maap.py takes "
                  f"the highest processID.")

    if failed:
        print(f"\n{len(set(failed))} module(s) did not register: "
              f"{', '.join(sorted(set(failed)))}")
        return 1

    print("\nDone. Run one job before trusting the rest -- the first job log "
          "prints the image build:\n    MUR image build: <sha>-<timestamp>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
