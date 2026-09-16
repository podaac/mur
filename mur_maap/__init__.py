"""MAAP/DPS execution support for the MUR SST pipeline.

run_mur_maap.py stays at the repo root and keeps the decision logic plus the
abstract MAAPClient interface; this package holds everything that talks to a
real service (maap-py, boto3, earthaccess) or persists run state, so the
orchestrator and its tests keep importing and running with no MAAP installed.

Submodules import lazily where they need an optional dependency -- importing
`mur_maap` itself must never require maap-py or boto3.
"""

from . import paths  # noqa: F401  -- pure stdlib, always safe to import

__all__ = ["paths"]
