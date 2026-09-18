"""Where the viewer finds granules, and how it gets them onto local disk.

The viewer has always browsed one directory tree and compared two files the
user picked by hand. That works while both sides of a comparison happen to be
sitting on the same machine -- which stops being true the moment the pipeline
runs on MAAP, and was never true of the thing most worth comparing against:
the operational MUR L4 product published at PO.DAAC.

This module separates *what a granule is* from *where it lives*.

    Granule   an id, a date, a mode, and an href that may be a local path, an
              ``s3://`` key or an ``https://`` URL.
    Catalog   knows how to search for Granules and how to materialize one as
              a local ``Path``.

Everything downstream -- the format readers, the full-resolution diff, the
plots -- keeps operating on local paths and never learns that a file arrived
from a catalogue. That is deliberate: ``build_full_res_diff`` opens the two
files with ``netCDF4.Dataset`` and reads them in row chunks, so a lazy remote
handle would have to satisfy the whole HDF5 read path. Downloading once into
a content-addressed cache is both simpler and, for a file read in thousands
of chunks, faster.

Three catalogs:

    LocalCatalog      the filesystem tree the viewer has always browsed
    MaapStacCatalog   MUR runs published to MAAP's STAC (or, failing an API,
                      the deterministic item keys in the workspace bucket)
    PublicMurCatalog  the operational MUR L4 product at PO.DAAC

Optional dependencies (``earthaccess``, ``s3fs``, ``requests``) are imported
inside the methods that need them, so importing this module -- and running the
local-only viewer -- never requires any of them.
"""
import datetime
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    from .viewer_config import ViewerConfig
except ImportError:
    # Streamlit runs web_viewer.py as a top-level script rather than as a
    # package module, so the relative import has no parent package to resolve
    # against. web_viewer.py already carries the same fallback; this module is
    # imported from there, so it needs it too.
    from viewer_config import ViewerConfig

#: ``20260303090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc``
#: The same convention for our own output (mrva/src/matlab/output/pushL44.m)
#: and for PO.DAAC's, which is exactly why the two are comparable at all.
L4_NAME_RE = re.compile(
    r"^(?P<stamp>\d{14})-JPL-L4_GHRSST-SSTfnd-(?P<product>MUR25|MUR)-GLOB-"
    r"v(?P<gds>[\d.]+)-fv(?P<version>[\d.]+)\.nc4?$"
)

PROGRESS = Optional[Callable[[float, str], None]]


class CatalogError(RuntimeError):
    """A catalog operation failed in a way worth showing the user."""


class CatalogUnavailable(CatalogError):
    """A catalog is not usable here -- missing dependency, credential or setting.

    Distinct from CatalogError because it is a configuration statement, not a
    failure: the UI renders it as a hint next to the source selector rather
    than as an error.
    """


def parse_l4_date(name: str) -> Optional[datetime.date]:
    """Analysis date from a MUR L4 filename, or None if it isn't one."""
    match = L4_NAME_RE.match(Path(name).name)
    if not match:
        return None
    try:
        return datetime.datetime.strptime(
            match.group("stamp")[:8], "%Y%m%d"
        ).date()
    except ValueError:
        return None


def is_mur25(name: str) -> bool:
    match = L4_NAME_RE.match(Path(name).name)
    return bool(match and match.group("product") == "MUR25")


@dataclass(frozen=True)
class Granule:
    """A reference to one data file, wherever it lives."""

    id: str
    name: str
    href: str
    source: str
    date: Optional[datetime.date] = None
    #: "nrt" (interim) or "rea" (final) for our own runs; None for PO.DAAC,
    #: whose published granule carries no such distinction.
    mode: Optional[str] = None
    size: Optional[int] = None
    extra: Dict = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return not self.href.startswith(("s3://", "http://", "https://"))

    @property
    def local_path(self) -> Optional[Path]:
        return Path(self.href) if self.is_local else None

    def label(self) -> str:
        """Short one-line description for a selectbox."""
        bits = [self.name]
        if self.mode:
            bits.append(f"[{self.mode.upper()}]")
        if self.size:
            bits.append(f"({self.size / 1e6:.0f} MB)")
        return " ".join(bits)


def _human_size(n: Optional[int]) -> str:
    if not n:
        return "unknown size"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} GB"


class Catalog:
    """Common interface over the places granules come from."""

    #: Stable identifier, matching the config's source names.
    name = "catalog"
    #: Human label for the UI.
    title = "Catalog"

    def __init__(self, config: ViewerConfig):
        self.config = config

    # -- availability ----------------------------------------------------

    def check(self) -> Optional[str]:
        """None when the catalog is usable, else why it isn't.

        Never raises. This is called on every render to paint a status line,
        so a broken optional dependency has to come back as a message, not as
        an exception -- an `import earthaccess` that fails with something
        other than ImportError would otherwise take down the whole viewer,
        including the sources that were working fine.
        """
        try:
            return self._check()
        except Exception as exc:  # noqa: BLE001 -- see docstring
            return f"unavailable: {exc}"

    def _check(self) -> Optional[str]:
        """Subclass hook for :meth:`check`; may raise."""
        return None

    # -- discovery -------------------------------------------------------

    def search(self, start: datetime.date, end: datetime.date) -> List[Granule]:
        raise NotImplementedError

    def find_for_date(self, day: datetime.date,
                      exclude_href: Optional[str] = None) -> Optional[Granule]:
        """The single granule for one day, or None.

        Where several match (an NRT and a REA for the same day), the final
        reanalysis wins -- it is the better reference, and a caller wanting
        the interim can search the day and pick.

        `exclude_href` drops one candidate: with a local tree as the reference
        source, the run being compared is itself in that tree, and our output
        and the reference share a filename by convention, so the obvious
        match for a run's date is frequently the run. Excluding it turns a
        dead-end "same file" into the comparison the user meant.
        """
        matches = [g for g in self.search(day, day)
                   if g.date == day and g.href != exclude_href]
        if not matches:
            return None
        matches.sort(key=lambda g: (g.mode != "rea", g.name))
        return matches[0]

    # -- materialization -------------------------------------------------

    def fetch(self, granule: Granule, progress: PROGRESS = None) -> Path:
        """Return a local path for `granule`, downloading it if need be."""
        if granule.is_local:
            path = granule.local_path
            if path is None or not path.exists():
                raise CatalogError(f"{granule.name}: file is gone")
            return path
        return self._download(granule, progress)

    def _download(self, granule: Granule, progress: PROGRESS) -> Path:
        raise NotImplementedError

    # -- cache -----------------------------------------------------------

    def cache_path(self, granule: Granule) -> Path:
        """Where a remote granule is materialized.

        Namespaced by source so the same filename fetched from PO.DAAC and
        from a MAAP run cannot collide -- which, given both sides of a
        comparison use the identical L4 naming convention, they otherwise
        certainly would.
        """
        year = granule.date.year if granule.date else "undated"
        return self.config.cache_dir / granule.source / str(year) / granule.name

    def _cached(self, granule: Granule) -> Optional[Path]:
        path = self.cache_path(granule)
        if not path.exists():
            return None
        # A size we know and don't match means a truncated download from an
        # interrupted session; re-fetch rather than hand back half a file.
        if granule.size and path.stat().st_size != granule.size:
            return None
        return path

    def _guard_size(self, granule: Granule) -> None:
        limit = self.config.max_download_mb * 1024 * 1024
        if granule.size and limit and granule.size > limit:
            raise CatalogError(
                f"{granule.name} is {_human_size(granule.size)}, over the "
                f"{self.config.max_download_mb} MB download limit "
                f"(raise MUR_VIEWER_MAX_DOWNLOAD_MB to allow it)"
            )


class LocalCatalog(Catalog):
    """MUR L4 granules on the filesystem the viewer is running on."""

    name = "local"
    title = "Local filesystem"

    def _check(self) -> Optional[str]:
        base = self.config.base_dir
        if not base.exists():
            return f"base directory does not exist: {base}"
        if not base.is_dir():
            return f"base directory is not a directory: {base}"
        return None

    def _candidates(self) -> List[Path]:
        base = self.config.base_dir
        if not base.is_dir():
            return []
        # rglob over an arbitrarily deep output tree can be slow on a network
        # mount, so cap the walk rather than risk a multi-minute render.
        found: List[Path] = []
        for pattern in ("*.nc", "*.nc4", "*/*.nc", "*/*.nc4",
                        "*/*/*.nc", "*/*/*.nc4", "*/*/*/*.nc", "*/*/*/*.nc4"):
            try:
                found.extend(base.glob(pattern))
            except (PermissionError, OSError):
                continue
        return found

    def search(self, start: datetime.date, end: datetime.date) -> List[Granule]:
        out: List[Granule] = []
        for path in self._candidates():
            day = parse_l4_date(path.name)
            if day is None or not (start <= day <= end):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            out.append(Granule(
                id=str(path),
                name=path.name,
                href=str(path),
                source=self.name,
                date=day,
                size=size,
                extra={"mur25": is_mur25(path.name)},
            ))
        out.sort(key=lambda g: (g.date or datetime.date.min, g.name),
                 reverse=True)
        return out

    def granule_for_path(self, path: Path) -> Granule:
        """Wrap an arbitrary already-selected file as a Granule.

        The file browser hands back paths for every format the viewer reads,
        not just L4 NetCDF, so this does not require the name to parse.
        """
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        return Granule(
            id=str(path), name=path.name, href=str(path), source=self.name,
            date=parse_l4_date(path.name), size=size,
        )


class PublicMurCatalog(Catalog):
    """The operational MUR L4 product, from PO.DAAC via CMR.

    Searching CMR needs no credentials; downloading does. The two are kept
    apart so the UI can list what exists for a date and only ask about
    Earthdata login at the moment a file is actually wanted.
    """

    name = "public"
    title = "PO.DAAC public product"

    def _check(self) -> Optional[str]:
        try:
            import earthaccess  # noqa: F401
        except ImportError:
            return ("earthaccess is not installed "
                    "(pip install 'earthaccess>=0.9')")
        return None

    def _auth(self):
        import earthaccess
        try:
            auth = earthaccess.login(strategy="netrc")
        except Exception:
            auth = None
        if auth is None or not getattr(auth, "authenticated", False):
            try:
                auth = earthaccess.login(strategy="environment")
            except Exception:
                auth = None
        if auth is None or not getattr(auth, "authenticated", False):
            raise CatalogUnavailable(
                "Earthdata login required to download from PO.DAAC. Add a "
                "machine urs.earthdata.nasa.gov entry to ~/.netrc, or set "
                "EARTHDATA_USERNAME / EARTHDATA_PASSWORD."
            )
        return auth

    def search(self, start: datetime.date, end: datetime.date) -> List[Granule]:
        try:
            import earthaccess
        except ImportError as exc:
            raise CatalogUnavailable(
                "earthaccess is not installed (pip install earthaccess)"
            ) from exc

        try:
            results = earthaccess.search_data(
                short_name=self.config.public_collection,
                temporal=(start.strftime("%Y-%m-%d"),
                          end.strftime("%Y-%m-%d")),
            )
        except Exception as exc:
            raise CatalogError(
                f"CMR search for {self.config.public_collection} failed: {exc}"
            ) from exc

        out: List[Granule] = []
        for item in results:
            links = self._data_links(item)
            if not links:
                continue
            https = next((u for u in links if u.startswith("http")), None)
            s3 = next((u for u in links if u.startswith("s3://")), None)
            href = (s3 if self.config.public_use_s3 and s3 else https) or links[0]
            name = href.rsplit("/", 1)[-1]
            day = parse_l4_date(name)
            if day is None or not (start <= day <= end):
                continue
            out.append(Granule(
                id=name, name=name, href=href, source=self.name, date=day,
                size=self._size(item),
                # The CMR result is carried along because handing it back to
                # earthaccess at download time is what lets earthaccess pick
                # the access route itself: direct S3 when running in
                # us-west-2, an HTTPS download otherwise. Reconstructing that
                # decision from a bare URL means re-deriving the provider and
                # the in-region test, and getting either wrong fails only on
                # the machine you are not testing on.
                extra={"https": https, "s3": s3, "_result": item,
                       "collection": self.config.public_collection},
            ))
        out.sort(key=lambda g: (g.date or datetime.date.min, g.name),
                 reverse=True)
        return out

    @staticmethod
    def _data_links(item) -> List[str]:
        """Data URLs for a CMR result, across earthaccess versions.

        `data_links` gained its `access` argument over time and raises on
        some combinations, so ask for what we want and fall back rather than
        pinning a version.
        """
        links: List[str] = []
        for kwargs in ({"access": "external"}, {"access": "direct"}, {}):
            try:
                found = item.data_links(**kwargs)
            except Exception:
                continue
            for url in found or []:
                if url not in links:
                    links.append(url)
        return [u for u in links if u.endswith((".nc", ".nc4"))] or links

    @staticmethod
    def _size(item) -> Optional[int]:
        try:
            mb = float(item.size())
        except Exception:
            return None
        return int(mb * 1024 * 1024) if mb else None

    def _download(self, granule: Granule, progress: PROGRESS) -> Path:
        cached = self._cached(granule)
        if cached is not None:
            if progress:
                progress(1.0, f"{granule.name} (cached)")
            return cached
        self._guard_size(granule)

        import earthaccess
        auth = self._auth()
        target = self.cache_path(granule)
        target.parent.mkdir(parents=True, exist_ok=True)

        if progress:
            progress(0.0, f"Downloading {granule.name} "
                          f"({_human_size(granule.size)}) from PO.DAAC…")

        # Stage into a scratch directory rather than straight into the cache:
        # an interrupted download would otherwise leave a short file sitting
        # under the name the cache looks for, and MUR L4 is ~700 MB, so an
        # interrupted download is not a hypothetical.
        staging = target.parent / ".partial"
        staging.mkdir(parents=True, exist_ok=True)
        store = earthaccess.Store(auth)
        result = granule.extra.get("_result")
        try:
            # The result object resolves provider and access route on its
            # own; the URL list is the fallback for a Granule that came back
            # from session state without it.
            payload = [result] if result is not None else [granule.href]
            got = store.get(payload, local_path=str(staging))
        except Exception as exc:
            raise CatalogError(
                f"download of {granule.name} failed: {exc}"
            ) from exc

        path = _resolve_downloaded(got, target)
        try:
            staging.rmdir()
        except OSError:
            pass
        if progress:
            progress(1.0, f"{granule.name} ready")
        return path


class MaapStacCatalog(Catalog):
    """MUR runs this pipeline published, discovered through MAAP.

    Two discovery routes, tried in order:

      1. A STAC API ``/search``, when ``maap_stac_url`` is set. Plain HTTP
         against the STAC spec rather than pystac-client, to avoid a new hard
         dependency for one POST.
      2. The deterministic item keys in the workspace bucket
         (``mur/stac/items/<year>/<doy><mode>.json``, from
         mur_maap/paths.stac_item_key). This is what run_mur_maap.py actually
         writes today, and it works before any STAC API exists to point at --
         which, per docs/maap.html, is still the state of things.

    Route 2 is also the honest one while the MAAP client is stubbed: it reads
    files we know we wrote, at keys we chose.
    """

    name = "maap"
    title = "MAAP STAC"

    def _check(self) -> Optional[str]:
        if not self.config.maap_stac_url and not self.config.maap_workspace_root:
            return ("neither a STAC URL nor a workspace root is configured "
                    "(set MUR_VIEWER_MAAP_STAC_URL or "
                    "MUR_VIEWER_MAAP_WORKSPACE_ROOT)")
        if self.config.maap_workspace_root and not self.config.maap_stac_url:
            try:
                import s3fs  # noqa: F401
            except ImportError:
                return "s3fs is not installed (pip install s3fs)"
        return None

    # -- route 1: STAC API ------------------------------------------------

    def _search_api(self, start: datetime.date,
                    end: datetime.date) -> List[Granule]:
        import requests

        url = self.config.maap_stac_url.rstrip("/") + "/search"
        payload = {
            "collections": [self.config.maap_collection],
            "datetime": (f"{start.isoformat()}T00:00:00Z/"
                         f"{end.isoformat()}T23:59:59Z"),
            "limit": 500,
        }
        headers = {"Content-Type": "application/json"}
        if self.config.maap_stac_token:
            headers["Authorization"] = f"Bearer {self.config.maap_stac_token}"

        try:
            response = requests.post(url, json=payload, headers=headers,
                                     timeout=30)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise CatalogError(f"STAC search at {url} failed: {exc}") from exc

        return [g for g in (granule_from_stac_item(f, self.name)
                            for f in body.get("features", []))
                if g is not None]

    # -- route 2: workspace bucket ---------------------------------------

    def _search_bucket(self, start: datetime.date,
                       end: datetime.date) -> List[Granule]:
        fs = self._fs()
        root = self.config.maap_workspace_root.rstrip("/")
        out: List[Granule] = []
        for year in range(start.year, end.year + 1):
            prefix = f"{root}/mur/stac/items/{year}/"
            try:
                keys = fs.glob(prefix.replace("s3://", "") + "*.json")
            except Exception:
                continue
            for key in keys:
                try:
                    with fs.open(key, "r") as fh:
                        item = json.load(fh)
                except Exception:
                    continue
                granule = granule_from_stac_item(item, self.name)
                if granule and granule.date and start <= granule.date <= end:
                    out.append(granule)
        return out

    def _fs(self):
        try:
            import s3fs
        except ImportError as exc:
            raise CatalogUnavailable(
                "s3fs is not installed (pip install s3fs)"
            ) from exc
        return s3fs.S3FileSystem(anon=False)

    def search(self, start: datetime.date, end: datetime.date) -> List[Granule]:
        reason = self.check()
        if reason:
            raise CatalogUnavailable(reason)

        errors = []
        if self.config.maap_stac_url:
            try:
                found = self._search_api(start, end)
                if found or not self.config.maap_workspace_root:
                    return _sorted_granules(found)
            except CatalogError as exc:
                errors.append(str(exc))
        if self.config.maap_workspace_root:
            try:
                return _sorted_granules(self._search_bucket(start, end))
            except CatalogError as exc:
                errors.append(str(exc))
        if errors:
            raise CatalogError("; ".join(errors))
        return []

    def _download(self, granule: Granule, progress: PROGRESS) -> Path:
        cached = self._cached(granule)
        if cached is not None:
            if progress:
                progress(1.0, f"{granule.name} (cached)")
            return cached
        self._guard_size(granule)

        target = self.cache_path(granule)
        target.parent.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(0.0, f"Downloading {granule.name} "
                          f"({_human_size(granule.size)}) from MAAP…")

        partial = target.with_suffix(target.suffix + ".part")
        try:
            if granule.href.startswith("s3://"):
                self._fs().get(granule.href, str(partial))
            else:
                _http_download(granule.href, partial,
                               self.config.maap_stac_token, progress,
                               granule.size)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise CatalogError(
                f"download of {granule.name} failed: {exc}"
            ) from exc

        partial.replace(target)
        if progress:
            progress(1.0, f"{granule.name} ready")
        return target


def granule_from_stac_item(item: Dict, source: str) -> Optional[Granule]:
    """Convert a STAC Item into a Granule.

    Kept a module-level function, not a method, so it can be tested against
    the Items mur_maap/stac.py builds without a catalog, a config or a
    network.
    """
    if not isinstance(item, dict):
        return None
    assets = item.get("assets") or {}
    asset = assets.get("data")
    if asset is None:
        # Any asset with a data role will do; the key is only a convention.
        for candidate in assets.values():
            if "data" in (candidate.get("roles") or []):
                asset = candidate
                break
    if not asset or not asset.get("href"):
        return None

    props = item.get("properties") or {}
    day = None
    stamp = props.get("datetime")
    if isinstance(stamp, str):
        try:
            day = datetime.datetime.fromisoformat(
                stamp.replace("Z", "+00:00")
            ).date()
        except ValueError:
            day = None

    href = asset["href"]
    name = href.rsplit("/", 1)[-1]
    if day is None:
        day = parse_l4_date(name)

    return Granule(
        id=item.get("id") or name,
        name=name,
        href=href,
        source=source,
        date=day,
        mode=(props.get("mur:mode") or "").lower() or None,
        size=asset.get("file:size"),
        extra={
            "job_id": props.get("mur:job_id"),
            "run_type": props.get("mur:run_type"),
            "collection": item.get("collection"),
        },
    )


def _sorted_granules(granules: List[Granule]) -> List[Granule]:
    return sorted(granules,
                  key=lambda g: (g.date or datetime.date.min, g.name),
                  reverse=True)


def _http_download(url: str, target: Path, token: str,
                   progress: PROGRESS, expected: Optional[int]) -> None:
    import requests

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with requests.get(url, headers=headers, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = expected or int(resp.headers.get("content-length") or 0)
        done = 0
        with target.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=8 << 20):
                fh.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(done / total, 1.0),
                             f"{_human_size(done)} / {_human_size(total)}")


def _resolve_downloaded(got, target: Path) -> Path:
    """Normalize whatever earthaccess returned onto `target`.

    `Store.get` returns a list of local paths, but the name and directory it
    chose are its own business; move the result to the cache path the viewer
    addresses so `_cached` can find it next time.
    """
    paths = [Path(p) for p in (got or []) if p]
    existing = [p for p in paths if p.exists()]
    if not existing:
        raise CatalogError(f"download produced no file for {target.name}")
    source = existing[0]
    if source.resolve() != target.resolve():
        shutil.move(str(source), str(target))
    return target


CATALOGS = {
    LocalCatalog.name: LocalCatalog,
    PublicMurCatalog.name: PublicMurCatalog,
    MaapStacCatalog.name: MaapStacCatalog,
}


def get_catalog(name: str, config: ViewerConfig) -> Catalog:
    try:
        return CATALOGS[name](config)
    except KeyError as exc:
        raise CatalogError(f"unknown catalog {name!r}") from exc


def cache_summary(config: ViewerConfig) -> Dict:
    """Files and bytes currently cached, for the sidebar's cache controls."""
    root = config.cache_dir
    if not root.is_dir():
        return {"files": 0, "bytes": 0, "path": root}
    files = [p for p in root.rglob("*") if p.is_file()]
    return {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "path": root,
        "human": _human_size(sum(p.stat().st_size for p in files)),
    }


def clear_cache(config: ViewerConfig) -> int:
    """Delete every cached granule; returns how many files went."""
    root = config.cache_dir
    if not root.is_dir():
        return 0
    count = sum(1 for p in root.rglob("*") if p.is_file())
    shutil.rmtree(root, ignore_errors=True)
    return count
