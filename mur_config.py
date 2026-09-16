"""Config loading and key-spelling normalization shared by
run_mur_pipeline.py (local `docker run` executor) and run_mur_maap.py
(MAAP/DPS executor).

The two orchestrators grew independently and read three settings under
different names:

    concept                pipeline spelling      MAAP spelling
    ------------------------------------------------------------------
    static-resources root  static_resources_dir   static_resources_root
    iQuam +/- window       buoy_dayrange          buoy_day_range
    iQuam stability        stable_latency         stability_latency

Only the pipeline spellings appear in the live config files (config.json,
config.example.json, config.container.json); only the MAAP spellings appear
in run_mur_maap.py and its test fixture. Rather than a flag-day rename of
both, normalize_config() accepts either and emits the canonical (live-config)
spelling, leaving every other key untouched.

This also closes a latent KeyError: run_mur_maap.py reads
config["landice"]["static_resources_root"], which exists in no config file
on disk, so the first real MAAP run would have raised before submitting
anything.
"""
import hashlib
import json
import pathlib
from typing import Any, Dict, Tuple

# (section, canonical_key, alias_key). The canonical spelling is the one the
# live config files already ship, so no existing config needs editing.
_KEY_ALIASES: Tuple[Tuple[str, str, str], ...] = (
    ("landice", "static_resources_dir", "static_resources_root"),
    ("mrva", "static_resources_dir", "static_resources_root"),
    ("iquam", "buoy_dayrange", "buoy_day_range"),
    ("iquam", "stable_latency", "stability_latency"),
)


def normalize_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of `raw` with alias keys folded onto canonical ones.

    Non-destructive: unknown keys pass through untouched, and an alias is
    only applied when the canonical key is absent, so a config that
    (confusingly) sets both keeps the canonical value.
    """
    config = json.loads(json.dumps(raw))  # deep copy; config is plain JSON
    for section, canonical, alias in _KEY_ALIASES:
        block = config.get(section)
        if not isinstance(block, dict):
            continue
        if canonical not in block and alias in block:
            block[canonical] = block[alias]
    return config


def get(config: Dict[str, Any], section: str, key: str, default: Any = None) -> Any:
    """Read a possibly-aliased setting without caring which spelling is present.

    Prefer normalize_config() at load time; this is for the callers that
    receive an already-parsed dict they did not load (e.g. MAAPOrchestrator,
    whose __init__ takes a config rather than a path).
    """
    block = config.get(section) or {}
    if key in block:
        return block[key]
    for sec, canonical, alias in _KEY_ALIASES:
        if sec != section:
            continue
        if key == canonical and alias in block:
            return block[alias]
        if key == alias and canonical in block:
            return block[canonical]
    return default


def load_config(path) -> Dict[str, Any]:
    """Load a pipeline config JSON file and normalize its key spellings."""
    with pathlib.Path(path).open() as f:
        return normalize_config(json.load(f))


def config_fingerprint(config: Dict[str, Any]) -> str:
    """Stable sha256 over a config's normalized content.

    A resumed MAAP run must refuse to continue against an edited config:
    changing a sensor's day_range or the static-resources root mid-run
    silently changes what the already-submitted jobs mean. Key *order* must
    not affect the result, so this sorts keys.
    """
    normalized = normalize_config(config)
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
