"""Locating a specific file inside a DPS job's staged-out directory.

`get_job_result()` returns a directory prefix, not per-file hrefs -- so a
job's named outputs cannot be fetched by name. The directory is listed and
filenames are matched instead. Observed for a real mur-landice job:

    <prefix>/
      outputs_result-<ts>.context.json     DPS sidecars
      outputs_result-<ts>.dataset.json
      outputs_result-<ts>.met.json
      _stdout.txt
      _stderr.txt
      p01/2026/
        Global_ice_2026_164.bip.gz
        icefiles_2026_164.txt
        landiceP01_2026_164.gds.gz
      p011/2026/
        Global_ice_2026_164.bip.gz
        icefiles_2026_164.txt
        landice_2026_164.gds.gz

Three things that are easy to get wrong, all encoded below:

  - The `output/` directory the container writes is flattened by DPS; its
    CONTENTS are the job directory, so patterns start at `p01/`, not
    `output/p01/`.
  - There is a <year> level under each resolution.
  - The two resolutions name the grid file differently: p01 carries a "P01"
    infix (landiceP01_), p011 does not (landice_). Matching one pattern
    against both would silently resolve the wrong resolution's file.

CONFIDENCE: the landice patterns are confirmed against a real job. The other
three modules are inferred from the filenames local runs produce and should be
verified the same way -- run one job, list the directory, correct the pattern.
"""
import datetime
import posixpath
import re
from typing import Dict, Iterable, List, Optional, Tuple

# DPS writes these alongside the real outputs. They match nothing below, but
# excluding them keeps "no match" diagnostics readable.
SIDECAR = re.compile(r"(^|/)(_std(out|err)\.txt|outputs_result-[^/]*\.(context|dataset|met)\.json)$")


def parse_dps_href(href: str) -> Tuple[str, str]:
    """Split a DPS result href into (bucket, key).

    MAAP returns `s3://<endpoint>:80/<bucket>/<key>`, not the usual
    `s3://<bucket>/<key>`. Splitting on the first slash after the scheme
    yields a "bucket" of `s3-us-west-2.amazonaws.com:80`, which then fails as
    a NoSuchBucket much later. Both forms are accepted here.
    """
    if "://" not in href:
        raise ValueError(f"not a URI: {href!r}")
    rest = href.split("://", 1)[1]
    head, _, tail = rest.partition("/")
    if ".amazonaws.com" in head or ":" in head:
        bucket, _, key = tail.partition("/")
        return bucket, key
    return head, tail


def result_prefix(result: Dict) -> str:
    """The s3:// href out of a get_job_result() body.

    The top-level key is a placeholder name (`additionalProp1` in the
    observed response), so the entry is taken positionally rather than by
    name. Each entry carries several links -- an S3 website URL, an s3://
    URI and a console URL -- and only the s3:// one is machine-usable.
    """
    if not result:
        raise ValueError("empty job result")
    entry = next(iter(result.values()))
    links = entry.get("links") or []
    for link in links:
        href = link.get("href", "")
        if href.startswith("s3://"):
            return href
    raise ValueError(f"no s3:// link in job result entry: {sorted(entry)}")


# Per-process filename patterns, relative to the staged-out directory.
# `{year}` and `{doy}` are substituted before matching.
OUTPUT_PATTERNS: Dict[str, Dict[str, str]] = {
    # Confirmed against a real job (2026/164).
    "mur-landice": {
        "landice_ice_p011": r"^p011/{year}/Global_ice_{year}_{doy}\.bip(\.gz)?$",
        # p01 carries the "P01" infix; p011 does not. Anchoring on the
        # resolution directory alone would match either.
        "landice_grid_p01": r"^p01/{year}/landiceP01_{year}_{doy}\.gds(\.gz)?$",
        "landice_icefiles_p011": r"^p011/{year}/icefiles_{year}_{doy}\.txt$",
        # Available but not currently consumed by MRVA.
        "landice_ice_p01": r"^p01/{year}/Global_ice_{year}_{doy}\.bip(\.gz)?$",
        "landice_grid_p011": r"^p011/{year}/landice_{year}_{doy}\.gds(\.gz)?$",
    },
    # PROVISIONAL -- inferred from local output, not yet seen on DPS.
    "mur-iquam": {
        "output": r"^iquam/{year}/Global_IQUAM0_{year}_{doy}\.bii$",
    },
    "mur-l2p": {
        "bic": r"^Global_{sensor}_{year}_{doy}\.bic(\.gz)?$",
        "l2plist": r"^L2Plist_\w+_{sensor}_{year}_{doy}\.txt$",
    },
    "mur-mrva": {
        "netcdf": r"^netcdf/.*{date}.*\.nc$",
        "csp": r"^csp/.*\.c\d\d$",
    },
}


def _fill(pattern: str, *, year=None, doy=None, sensor=None, date=None) -> str:
    return pattern.format(
        year=year if year is not None else r"\d{4}",
        doy=f"{doy:03d}" if isinstance(doy, int) else (doy or r"\d{3}"),
        sensor=sensor or r"\w+",
        date=date or r"\d{8}",
    )


def relative_keys(keys: Iterable[str], prefix: str) -> List[str]:
    """Strip the job prefix and drop DPS's sidecar files."""
    prefix = prefix.rstrip("/") + "/"
    out = []
    for key in keys:
        rel = key[len(prefix):] if key.startswith(prefix) else key
        if rel and not SIDECAR.search(rel):
            out.append(rel)
    return out


def resolve_output(
    keys: Iterable[str],
    process_id: str,
    output_name: str,
    *,
    prefix: str = "",
    **fmt,
) -> str:
    """The single key matching `output_name`, or raise explaining why not.

    Raises rather than guessing on both zero and multiple matches: a wrong
    file here is fed to MRVA as though it were the right one, which is far
    worse than a failed lookup.
    """
    try:
        pattern = OUTPUT_PATTERNS[process_id][output_name]
    except KeyError:
        known = sorted(OUTPUT_PATTERNS.get(process_id, {}))
        raise KeyError(
            f"no pattern for {output_name!r} on {process_id!r}; known: {known}"
        ) from None

    rx = re.compile(_fill(pattern, **fmt))
    rels = relative_keys(keys, prefix) if prefix else list(keys)
    hits = [r for r in rels if rx.search(r)]

    if len(hits) == 1:
        return posixpath.join(prefix.rstrip("/"), hits[0]) if prefix else hits[0]
    raise LookupError(
        f"{output_name!r} on {process_id!r}: expected 1 match for "
        f"{rx.pattern!r}, found {len(hits)}"
        + (f" ({hits})" if hits else f"; available: {sorted(rels)[:20]}")
    )


def resolve_all(
    keys: Iterable[str],
    process_id: str,
    *,
    prefix: str = "",
    **fmt,
) -> Dict[str, str]:
    """Every output this process defines that is actually present.

    Unlike resolve_output, a missing output is omitted rather than raised --
    for reporting what a job produced, where absence is information.
    """
    found = {}
    for name in OUTPUT_PATTERNS.get(process_id, {}):
        try:
            found[name] = resolve_output(
                keys, process_id, name, prefix=prefix, **fmt)
        except LookupError:
            continue
    return found
