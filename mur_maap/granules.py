"""Finding PO.DAAC L2P granules for a day.

Discovery only. This module resolves a sensor-day to a list of s3:// hrefs and
stops there -- it never opens one. The container fetches them: localize.sh
dispatches on each manifest entry's access kind and mints DAAC credentials
from a MAAP token when a source needs them.

That split is the point, not an optimization. Data access belongs to whatever
is going to read the data, so the container works the same way wherever it
runs: given a mounted path it reads the file, given a public bucket it uses the
runtime's own credentials, given a DAAC bucket it obtains the credentials that
bucket requires. The orchestrator never has to know which environment it is in,
and nothing here needs credentials for a bucket it does not read.

The earlier design copied every granule into the workspace bucket first, to
work around a DPS worker's role getting 403 on PO.DAAC. That made this process
responsible for moving tens of gigabytes a day and left a second copy of
PO.DAAC behind. The container solving its own access problem removes both.
"""

import datetime
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

_warned_obsolete_mode = False


class GranuleDiscoveryError(RuntimeError):
    pass


def discover_day(
    collections: List[str],
    data_day: datetime.date,
    *,
    collection_filter: Optional[str] = None,
) -> List[str]:
    """PO.DAAC s3:// hrefs for one sensor-day, straight from CMR.

    Metadata only. The hrefs point at PO.DAAC's own bucket and are handed to
    the job as manifest entries with access kind "podaac".
    """
    try:
        import earthaccess
    except ImportError:
        raise GranuleDiscoveryError(
            "earthaccess is required for granule discovery. "
            "pip install earthaccess") from None

    # Discovery is metadata, not data: CMR serves public collections
    # anonymously, so a login is an optimization rather than a requirement.
    # Try the usual sources and carry on without one -- demanding a .netrc
    # for a search that does not need it is a needless obstacle.
    _try_login(earthaccess)

    hrefs: List[str] = []
    for collection in collections:
        if collection_filter and collection != collection_filter:
            continue
        results = earthaccess.search_data(
            short_name=collection,
            temporal=(f"{data_day.isoformat()}T00:00:00Z",
                      f"{data_day.isoformat()}T23:59:59Z"),
        )
        kept = 0
        for granule in results:
            # access="direct" yields the s3:// href; "external" would give an
            # https:// one. Both are fetchable now, but s3:// avoids egress
            # and is what the podaac access kind is built around.
            links = [link for link in granule.data_links(access="direct")
                     if link.endswith(".nc")]
            # CMR's temporal search matches on OVERLAP, so the 23:5x granule
            # that started yesterday and ends today comes back for both days.
            # Production files a granule under its START day only
            # (podaac-data-subscriber -dydoy, mur_cron/*.sh), and l2p2bic
            # reads that one directory -- so keeping the overlap put the
            # previous day's last swath into this BIC as well (AVMTBG
            # 2026/291: two extra granules, ~7% more points than prod).
            if starts_on(granule, links, data_day) is False:
                continue
            kept += 1
            hrefs.extend(links)
        logger.info("    %s %s: %d granule(s) in CMR, %d starting that day",
                    collection, data_day, len(results), kept)
    return sorted(set(hrefs))


def starts_on(granule, links: List[str], data_day: datetime.date) -> Optional[bool]:
    """Whether a CMR result begins on `data_day`; None when it cannot be told.

    The UMM BeginningDateTime is the authority. The GHRSST filename, which
    leads with the start time (20261020235501-JPL-L2P_...), is the fallback.
    None keeps the granule: dropping one whose date could not be read would
    be a silent loss, and the overlap it guards against is one swath a day.
    """
    try:
        begin = (granule["umm"]["TemporalExtent"]["RangeDateTime"]
                 ["BeginningDateTime"])
        return datetime.date.fromisoformat(str(begin)[:10]) == data_day
    except (KeyError, TypeError, ValueError):
        pass
    for link in links:
        stem = link.rsplit("/", 1)[-1][:8]
        if stem.isdigit():
            try:
                return datetime.datetime.strptime(stem, "%Y%m%d").date() == data_day
            except ValueError:
                continue
    return None


def _try_login(earthaccess) -> bool:
    """Best-effort Earthdata login. False just means "searching anonymously"."""
    for strategy in ("environment", "netrc"):
        try:
            earthaccess.login(strategy=strategy)
            logger.debug("earthaccess login via %s", strategy)
            return True
        except Exception:                                 # noqa: BLE001
            continue
    logger.debug("no Earthdata login; searching CMR anonymously")
    return False


def granules_for_day(
    client,
    sensor: str,
    collections: List[str],
    data_day: datetime.date,
    *,
    mode: str = "direct",
    workdir=None,
    collection_filter: Optional[str] = None,
) -> List[str]:
    """PO.DAAC hrefs for this sensor-day. The container fetches them itself.

    `mode` and `workdir` are accepted so existing configs and call sites keep
    working, and otherwise ignored: there is one path now.
    """
    # Once per process, not once per sensor-day: a run is 5 sensors x 5 days,
    # and 25 copies of the same notice buries the log lines that matter.
    global _warned_obsolete_mode
    if mode == "workspace" and not _warned_obsolete_mode:
        _warned_obsolete_mode = True
        logger.info(
            "    granule_staging=workspace is obsolete -- the container reads "
            "PO.DAAC directly. Discovering only. (Set maap.granule_staging to "
            "\"direct\" to silence this.)")
    return discover_day(collections, data_day,
                        collection_filter=collection_filter)
