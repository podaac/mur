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
        for granule in results:
            # access="direct" yields the s3:// href; "external" would give an
            # https:// one. Both are fetchable now, but s3:// avoids egress
            # and is what the podaac access kind is built around.
            for link in granule.data_links(access="direct"):
                if link.endswith(".nc"):
                    hrefs.append(link)
        logger.info("    %s %s: %d granule(s) in CMR",
                    collection, data_day, len(results))
    return sorted(set(hrefs))


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
