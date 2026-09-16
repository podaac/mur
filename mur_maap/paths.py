"""Canonical S3 key and href construction for everything the MAAP
orchestrator writes to, or looks for in, the workspace bucket.

Every path the orchestrator builds lives here so that the layout is stated
once. Before this module, run_mur_maap.py built a bucket-relative key
(`mur/bic/AMSR2R/2026/218.bic.gz`), passed it to `object_exists` (which is
documented as taking an `s3_uri`), and then separately made an href out of it
with `f"s3://{bic_prefix}"` -- producing `s3://mur/bic/...`, i.e. a bucket
literally named "mur". That silently looked for the cached BIC in a bucket
that does not exist, so the cache never hit.

Two vocabularies, kept deliberately distinct:

  key   bucket-relative, e.g. "mur/bic/AMSR2R/2026/218.bic.gz".
        What write_manifest() addresses, since the client already knows the
        bucket.
  href  a full "s3://bucket/key" URI. What goes into manifests and job args,
        because the containers' localize.sh hands it straight to `aws s3 cp`.
"""
import datetime
from typing import List, Tuple

MUR_ROOT = "mur"


def _doy(day: datetime.date) -> int:
    return day.timetuple().tm_yday


def href(workspace_root: str, key: str) -> str:
    """Join a workspace root ("s3://bucket/prefix") and a bucket-relative key."""
    return f"{workspace_root.rstrip('/')}/{key.lstrip('/')}"


def split_href(uri: str) -> Tuple[str, str]:
    """Split "s3://bucket/key" into (bucket, key)."""
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri!r}")
    bucket, _, key = uri[len("s3://"):].partition("/")
    return bucket, key


# --- BIC (L2P output, MRVA fan-in input) -----------------------------------

def bic_filename(sensor: str, data_day: datetime.date, compressed: bool = True) -> str:
    """The name l2p's writebic.m gives a BIC file.

    writebic.m emits an uncompressed `.bic`; production archives are `.bic.gz`
    and makebiq.m accepts either -- so callers generally want bic_candidates().
    """
    suffix = ".bic.gz" if compressed else ".bic"
    return f"Global_{sensor}_{data_day.year}_{_doy(data_day):03d}{suffix}"


def bic_key(sensor: str, data_day: datetime.date, compressed: bool = True) -> str:
    """Cache key for a day's BIC, ending in the file's REAL name.

    The key deliberately ends in `Global_<SENSOR>_<YEAR>_<DOY>.bic[.gz]` rather
    than a bare `<DOY>.bic.gz`: bic_relative_path() derives the in-container
    filename from the href's basename, and mrva4com_container.m's per-sensor
    directory scan matches on the `Global_<SENSOR>_...` convention that
    l2p/src/writebic.m produces. A key whose basename didn't match would
    materialize the file under a name the scan ignores.
    """
    return (f"{MUR_ROOT}/bic/{sensor}/{data_day.year}/"
            f"{bic_filename(sensor, data_day, compressed)}")


def bic_candidate_hrefs(workspace_root: str, sensor: str,
                        data_day: datetime.date) -> List[str]:
    """Cache-probe order for a day's BIC: compressed first, then plain.

    Mirrors run_mur_pipeline.py's build_mrva_sensor_manifest, which probes both
    and prefers `.gz`.
    """
    return [
        href(workspace_root, bic_key(sensor, data_day, compressed=True)),
        href(workspace_root, bic_key(sensor, data_day, compressed=False)),
    ]


def bic_relative_path(sensor: str, data_day: datetime.date, filename: str) -> str:
    """Where localize_manifest should materialize a BIC inside the container.

    mrva4com_container.m builds `<SENSOR>/<YEAR>/<file>` per-sensor directories
    and scans them, so the manifest must reproduce that layout. The filename is
    passed in rather than derived so it always matches the actual object -- a
    `.bic` that was guessed as `.bic.gz` would materialize under the wrong name
    and the per-sensor scan would miss it.
    """
    return f"{sensor}/{data_day.year}/{filename}"


# --- CSP coefficients (MRVA output, next day's --prior-csp-file) -----------

def csp_filename(process_date: datetime.date) -> str:
    """The name MRVA gives its L=6 coefficient file.

    Mirrors run_mur_pipeline.py's resolve_mrva_prior_csp, which looks for
    `<YYYYMMDD>09_MRVA4_Global.c06` under `<csp_dir>/<year>/`.
    """
    return f"{process_date.strftime('%Y%m%d')}09_MRVA4_Global.c06"


def csp_key(process_date: datetime.date) -> str:
    return f"{MUR_ROOT}/csp/{process_date.year}/{csp_filename(process_date)}"


def prior_csp_href(workspace_root: str, process_date: datetime.date) -> str:
    """Canonical href for the coefficient MRVA should chain from.

    Only meaningful in NRT mode -- REA never used a prior coefficient (see
    resolve_mrva_prior_csp). Absence is a valid state: mrva4com_container.m
    bootstraps instead.
    """
    prior_day = process_date - datetime.timedelta(days=1)
    return href(workspace_root, csp_key(prior_day))


# --- iQuam (IQUAM0 fan-in input) -------------------------------------------

def iquam_filename(data_day: datetime.date) -> str:
    return f"Global_IQUAM0_{data_day.year}_{_doy(data_day):03d}.bii"


def iquam_relative_path(data_day: datetime.date) -> str:
    """Note the year comes from the *data* day, not the analysis day.

    buoyDataProcessing.m writes `<outputDir>/<YYYY>/Global_IQUAM0_<YYYY>_<DDD>.bii`
    per day across its +/- window, so a window spanning a year boundary writes
    into two year directories.
    """
    return f"IQUAM0/{data_day.year}/{iquam_filename(data_day)}"


# --- manifests -------------------------------------------------------------

def l2p_manifest_key(sensor: str, data_day: datetime.date) -> str:
    return (f"{MUR_ROOT}/manifests/l2p/{sensor}/{data_day.year}/"
            f"{_doy(data_day):03d}.json")


def mrva_manifest_key(process_date: datetime.date) -> str:
    return (f"{MUR_ROOT}/manifests/mrva/{process_date.year}/"
            f"{_doy(process_date):03d}.json")


# --- staged L2P granules ---------------------------------------------------

def granule_stage_prefix(sensor: str, data_day: datetime.date) -> str:
    """Where PO.DAAC granules are re-staged so a DPS job can actually read them.

    localize.sh uses `aws s3 cp` on the default credential chain, which inside
    DPS is the job's own role -- not PO.DAAC's. All DAACs require temporary S3
    credentials via Earthdata Login, so granules are copied into the workspace
    bucket first (see mur_maap/granules.py).
    """
    return (f"{MUR_ROOT}/l2p-granules/{sensor}/{data_day.year}/"
            f"{_doy(data_day):03d}")


# --- run state / STAC ------------------------------------------------------

def run_state_key(run_id: str) -> str:
    return f"{MUR_ROOT}/runs/{run_id}/state.json"


def stac_item_key(process_date: datetime.date, mode: str) -> str:
    return (f"{MUR_ROOT}/stac/items/{process_date.year}/"
            f"{_doy(process_date):03d}{mode}.json")
