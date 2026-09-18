"""Configuration for where the viewer looks for data.

The viewer used to have exactly one setting -- ``MUR_BASE_DIR`` -- because it
had exactly one place to look: a directory tree on the machine running
Streamlit. Once the pipeline runs on MAAP and the thing worth comparing
against is the operational product at PO.DAAC, "where is the data" stops
being a single path and becomes three independent answers:

    run source        where the granule *we produced* comes from
                      ("local" filesystem, or "maap" STAC)
    reference source  where the granule we compare it *against* comes from
                      ("public" PO.DAAC, and "local"/"maap" for the cases
                      where you really do want run-vs-run)
    cache             where remote granules are materialized, since every
                      reader downstream wants a local path

Those are kept separate on purpose. Comparing a MAAP run against the public
product and comparing a local run against the public product are the same
operation with a different run source, and neither should require editing the
other half of the configuration.

Resolution order, most specific first:

    1. explicit keyword arguments to :func:`load_config`
    2. environment variables (``MUR_VIEWER_*``, plus the historical
       ``MUR_BASE_DIR``)
    3. a JSON config file -- ``MUR_VIEWER_CONFIG``, else ``./viewer.json``,
       else ``~/.config/mur-viewer/config.json``
    4. the defaults below

Environment beating the file matches how the viewer is actually deployed: the
file is checked in or baked into an image, and the env var is what the person
launching it overrides.
"""
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Optional

# PO.DAAC's operational MUR L4. This is the same product the pipeline
# reproduces, which is what makes it the useful default reference: a
# difference against it is a statement about the run, not about two
# arbitrary files that happened to be on disk.
DEFAULT_PUBLIC_COLLECTION = "MUR-JPL-L4-GLOB-v4.1"

# MAAP's STAC API. Configurable because MUR's own collection may end up on a
# project-specific endpoint rather than the shared one.
DEFAULT_MAAP_STAC_URL = "https://stac.maap-project.org"

# Matches mur_maap/stac.py's DEFAULT_COLLECTION -- the collection this
# pipeline publishes its L4 Items into.
DEFAULT_MAAP_COLLECTION = "mur-l4-sst"

RUN_SOURCES = ("local", "maap")
REFERENCE_SOURCES = ("public", "local", "maap")


def _default_cache_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(root) / "mur-viewer" / "granules"


@dataclass(frozen=True)
class ViewerConfig:
    """Resolved answer to "where does the viewer look for data".

    Frozen because it is read on every Streamlit rerun and nothing should be
    able to mutate it halfway through a render; the sidebar produces a new
    one via :meth:`with_overrides` instead.
    """

    # --- run source ---------------------------------------------------
    run_source: str = "local"
    base_dir: Path = field(default_factory=Path.cwd)

    # --- reference source ---------------------------------------------
    reference_source: str = "public"

    # --- public (PO.DAAC) ---------------------------------------------
    public_collection: str = DEFAULT_PUBLIC_COLLECTION
    #: Show the ``s3://`` href rather than the HTTPS one when listing.
    #: Display only: earthaccess picks the actual access route itself --
    #: direct S3 in us-west-2, an HTTPS download anywhere else -- so this
    #: does not need setting to get fast in-region reads on MAAP.
    public_use_s3: bool = False

    # --- MAAP ----------------------------------------------------------
    maap_stac_url: str = DEFAULT_MAAP_STAC_URL
    maap_collection: str = DEFAULT_MAAP_COLLECTION
    #: "s3://bucket/prefix" -- the workspace root run_mur_maap.py writes to.
    #: When set, the viewer can fall back to reading the deterministic STAC
    #: item keys (mur_maap/paths.stac_item_key) directly out of the bucket,
    #: which is what this pipeline actually writes today even where no STAC
    #: API is reachable.
    maap_workspace_root: str = ""
    maap_stac_token: str = ""

    # --- cache ----------------------------------------------------------
    cache_dir: Path = field(default_factory=_default_cache_dir)
    #: Refuse to download a granule larger than this without an explicit
    #: confirmation. MUR L4 is ~600 MB/day; a careless date range is a very
    #: expensive accident on a metered connection.
    max_download_mb: int = 2048

    #: Where the settings above actually came from, for display in the UI.
    source_file: Optional[Path] = None

    def with_overrides(self, **kwargs: Any) -> "ViewerConfig":
        """A copy with some fields replaced (used by the sidebar controls)."""
        clean = {k: v for k, v in kwargs.items() if v is not None}
        if "base_dir" in clean:
            clean["base_dir"] = Path(clean["base_dir"]).expanduser()
        if "cache_dir" in clean:
            clean["cache_dir"] = Path(clean["cache_dir"]).expanduser()
        return replace(self, **clean)


def _config_file_path(explicit: Optional[str] = None) -> Optional[Path]:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("MUR_VIEWER_CONFIG")
    if env:
        candidates.append(Path(env))
    candidates.append(Path.cwd() / "viewer.json")
    candidates.append(Path.home() / ".config" / "mur-viewer" / "config.json")
    for path in candidates:
        path = path.expanduser()
        if path.is_file():
            return path
    return None


def _read_config_file(path: Path) -> Dict[str, Any]:
    """Read a viewer config file.

    Accepts either a dedicated viewer config (flat keys, or nested under a
    ``"viewer"`` block) or a pipeline config that happens to have a ``maap``
    block -- so pointing the viewer at ``config.maap.json`` picks up the
    workspace root without duplicating it.
    """
    with path.open() as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")

    settings: Dict[str, Any] = {}

    maap_block = raw.get("maap")
    if isinstance(maap_block, dict):
        for src, dst in (
            ("workspace_root", "maap_workspace_root"),
            ("stac_url", "maap_stac_url"),
            ("stac_collection", "maap_collection"),
        ):
            if maap_block.get(src):
                settings[dst] = maap_block[src]

    viewer_block = raw.get("viewer")
    flat = viewer_block if isinstance(viewer_block, dict) else raw
    for key in (
        "run_source", "base_dir", "reference_source",
        "public_collection", "public_use_s3",
        "maap_stac_url", "maap_collection", "maap_workspace_root",
        "maap_stac_token", "cache_dir", "max_download_mb",
    ):
        if key in flat and flat[key] not in (None, ""):
            settings[key] = flat[key]
    return settings


_ENV_KEYS = {
    "MUR_VIEWER_RUN_SOURCE": "run_source",
    "MUR_BASE_DIR": "base_dir",
    "MUR_VIEWER_BASE_DIR": "base_dir",
    "MUR_VIEWER_REFERENCE_SOURCE": "reference_source",
    "MUR_VIEWER_PUBLIC_COLLECTION": "public_collection",
    "MUR_VIEWER_PUBLIC_USE_S3": "public_use_s3",
    "MUR_VIEWER_MAAP_STAC_URL": "maap_stac_url",
    "MUR_VIEWER_MAAP_COLLECTION": "maap_collection",
    "MUR_VIEWER_MAAP_WORKSPACE_ROOT": "maap_workspace_root",
    "MUR_VIEWER_MAAP_STAC_TOKEN": "maap_stac_token",
    "MUR_VIEWER_CACHE_DIR": "cache_dir",
    "MUR_VIEWER_MAX_DOWNLOAD_MB": "max_download_mb",
}

# MAAP's own conventional token variables, used when the viewer-specific one
# is unset so a MAAP JupyterHub session needs no extra configuration.
_MAAP_TOKEN_FALLBACKS = ("MAAP_PGT", "MAAP_API_TOKEN")

_BOOL_TRUE = {"1", "true", "yes", "on"}


def _env_settings(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env = os.environ if env is None else env
    settings: Dict[str, Any] = {}
    for var, key in _ENV_KEYS.items():
        value = env.get(var)
        if value in (None, ""):
            continue
        # MUR_VIEWER_BASE_DIR is the newer, namespaced spelling; when both
        # are set it wins over the historical MUR_BASE_DIR.
        if key == "base_dir" and var == "MUR_BASE_DIR" and env.get("MUR_VIEWER_BASE_DIR"):
            continue
        settings[key] = value
    if "maap_stac_token" not in settings:
        for var in _MAAP_TOKEN_FALLBACKS:
            if env.get(var):
                settings["maap_stac_token"] = env[var]
                break
    return settings


def _coerce(settings: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(settings)
    for key in ("base_dir", "cache_dir"):
        if key in out:
            out[key] = Path(str(out[key])).expanduser()
    if "public_use_s3" in out and not isinstance(out["public_use_s3"], bool):
        out["public_use_s3"] = str(out["public_use_s3"]).strip().lower() in _BOOL_TRUE
    if "max_download_mb" in out:
        out["max_download_mb"] = int(out["max_download_mb"])
    for key, allowed in (("run_source", RUN_SOURCES),
                         ("reference_source", REFERENCE_SOURCES)):
        if key in out:
            value = str(out[key]).strip().lower()
            if value not in allowed:
                raise ValueError(
                    f"{key}={value!r} is not one of {', '.join(allowed)}"
                )
            out[key] = value
    return out


def load_config(config_path: Optional[str] = None,
                env: Optional[Dict[str, str]] = None,
                **overrides: Any) -> ViewerConfig:
    """Resolve the viewer's data-source configuration.

    `overrides` beat the environment, which beats the config file, which
    beats the defaults. A bad value raises rather than being silently
    ignored -- a typo'd run source should be a visible error, not a quiet
    fallback to the local filesystem.
    """
    settings: Dict[str, Any] = {}

    path = _config_file_path(config_path)
    if path is not None:
        settings.update(_read_config_file(path))
        settings["source_file"] = path

    settings.update(_env_settings(env))
    settings.update({k: v for k, v in overrides.items() if v is not None})

    settings = _coerce(settings)
    if "base_dir" not in settings:
        settings["base_dir"] = Path.cwd()
    return ViewerConfig(**settings)


def describe(config: ViewerConfig) -> str:
    """One-line human summary, for the sidebar and for logs."""
    where = f" (from {config.source_file})" if config.source_file else ""
    return (f"runs: {config.run_source} · reference: {config.reference_source}"
            f"{where}")
