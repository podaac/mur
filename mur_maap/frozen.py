"""A frozen regression case: one prod run's inputs, replayed on MAAP.

utils/capture_prod_run.py snapshots a prod run on the ops disks, and
utils/stage_prod_snapshot.py uploads it and writes `case.json`. That file says
which days the run analysed and in which mode, which L2P granules each BIC was
built from, and where the two seeded data roots are. This module reads it and
answers the orchestrator's questions in frozen mode (run_mur_maap.py
--frozen-case).

There are two variants. Both use the registered containers unchanged.

  isolated  Every stage gets prod's own inputs: the BICs, .bii, landice and
            the prior c06 that prod's MRVA read. No L2P, landice or iquam job
            runs, and MRVA's c06 is NOT promoted, so day D+1 still sees prod's
            c06 for day D and not ours. A difference in the L4 is then MRVA's
            alone.
  chained   The run as ops runs it. Young BICs (newer than prod's stablat) are
            rebuilt by mur-l2p from the exact granules prod used. Stable ones,
            landice and .bii come from prod. c06 chains from MAAP's own REA
            day. The same young BICs compared with prod's are the L2P stage
            check.

What frozen mode never does, in either variant: query CMR, fetch live
OSI-SAF or iQUAM data, copy granules to the team bucket, publish STAC items,
or submit cog jobs. The case's data root is the only place it writes.
"""
import datetime
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

VARIANTS = ("isolated", "chained")
SCHEMA = 1


def tag(d: datetime.date) -> str:
    """'YYYY_DDD', the day label of prod's file names and the snapshot."""
    return f"{d.year:04d}_{d.timetuple().tm_yday:03d}"


def canonical_key(snapshot_rel: str) -> Optional[str]:
    """The data-root key for a file of a snapshot day, or None if the file is
    not an MRVA input.

    The snapshot keeps prod's file names and lays them out the way
    mur_maap/paths.py does, so this is a prefix change:
    bic/, iquam/ and landice/ stay as they are, and csp_prior/ becomes csp/.
    """
    head, _, rest = snapshot_rel.partition("/")
    if head in ("bic", "iquam", "landice"):
        if head == "bic" and rest.rsplit("/", 1)[-1].startswith("L2Plist_"):
            return None
        return f"mur/{snapshot_rel}"
    if head == "csp_prior":
        return f"mur/csp/{rest}"
    return None


@dataclass
class FrozenCase:
    data: Dict
    variant: str
    href: Optional[str] = None

    def __post_init__(self):
        if self.variant not in VARIANTS:
            raise ValueError(f"unknown frozen variant {self.variant!r}; "
                             f"one of {', '.join(VARIANTS)}")
        if self.data.get("schema") != SCHEMA:
            raise ValueError(f"case schema {self.data.get('schema')!r}, "
                             f"expected {SCHEMA}")
        if self.variant not in self.data.get("roots", {}):
            raise ValueError(f"case has no {self.variant} root")

    # -- what the case is --------------------------------------------------

    @property
    def run_date(self) -> datetime.date:
        return datetime.date.fromisoformat(self.data["run_date"])

    @property
    def days(self) -> Dict[datetime.date, str]:
        """Analysis day -> prod's mode for it."""
        return {datetime.date.fromisoformat(v["date"]): v["mode"]
                for v in self.data["days"].values()}

    @property
    def root(self) -> str:
        return self.data["roots"][self.variant].rstrip("/")

    @property
    def job_tag(self) -> str:
        """One Console batch per case and variant, which is also how the
        compare step finds this case's jobs."""
        return f"MUR-REGRESS-{self.run_date:%Y%m%d}-{self.variant}"

    # -- policy ------------------------------------------------------------

    @property
    def rebuilds_young_bics(self) -> bool:
        return self.variant == "chained"

    @property
    def promotes_csp(self) -> bool:
        return self.variant == "chained"

    def granules(self, sensor: str, data_day: datetime.date) -> Optional[List[str]]:
        """The granule hrefs prod built this BIC from, or None when prod had
        no L2Plist for it (then prod had no BIC either)."""
        per = self.data.get("granules", {}).get(sensor, {})
        got = per.get(tag(data_day))
        return list(got) if got is not None else None

    def check_days(self, days: List[datetime.date],
                   modes: Dict[datetime.date, str]) -> None:
        """Refuse a run that would not replay prod: a day prod did not analyse,
        or one in a different mode than prod's."""
        known = self.days
        for d in days:
            if d not in known:
                raise SystemExit(
                    f"{d} is not in the frozen case (it has "
                    f"{', '.join(str(k) for k in sorted(known))})")
            if modes[d] != known[d]:
                raise SystemExit(
                    f"{d}: this run would analyse it as {modes[d]}, prod ran "
                    f"{known[d]}. Use --date {self.run_date} so the window "
                    f"matches prod's run.")


def parse_case(text: str, variant: str, href: Optional[str] = None) -> FrozenCase:
    return FrozenCase(json.loads(text), variant, href)


def load_case(href: str, variant: str, s3=None) -> FrozenCase:
    """Read case.json from a local path or an s3:// href (with `s3`, a boto3
    client such as WorkspaceBucket.s3())."""
    if href.startswith("s3://"):
        if s3 is None:
            raise ValueError("an s3:// case needs an S3 client")
        bucket, _, key = href[5:].partition("/")
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode()
        return parse_case(body, variant, href)
    with open(href) as f:
        return parse_case(f.read(), variant, href)


def seed_plan(snapshot_days: Dict[str, List[Tuple[str, str]]],
              stablat: Dict[str, int],
              run_date: datetime.date) -> Dict[str, Dict[str, str]]:
    """Which snapshot file goes to which key in each variant's data root.

    `snapshot_days` maps a day tag to its captured (relative path, md5) pairs,
    in run order (oldest first, the order prod's MRVA ran in).

    When the same file was captured with different content on different days
    (a BIC rebuilt in the background-gzip race), the version from the EARLIEST
    day wins: that is the one prod's first reader saw, and both roots are
    shared by every day of the run. stage_prod_snapshot reports the conflict.

    Returns {variant: {canonical key: snapshot path "days/<tag>/<rel>"}}.
    """
    plan: Dict[str, Dict[str, str]] = {v: {} for v in VARIANTS}
    for day_tag in sorted(snapshot_days):
        for rel, _md5 in snapshot_days[day_tag]:
            key = canonical_key(rel)
            if key is None:
                continue
            src = f"days/{day_tag}/{rel}"
            plan["isolated"].setdefault(key, src)
            if rel.startswith("csp_prior/"):
                continue                     # chained makes its own c06
            if rel.startswith("bic/"):
                sensor, year, name = rel.split("/")[1:4]
                doy = int(name.split("_")[3].split(".")[0])
                data_day = datetime.date(int(year), 1, 1) + datetime.timedelta(days=doy - 1)
                if (run_date - data_day).days < stablat.get(sensor, 2):
                    continue                 # chained rebuilds it from the granules
            plan["chained"].setdefault(key, src)
    return plan
