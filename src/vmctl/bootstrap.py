"""Idempotent installation-time catalog initialization."""

from __future__ import annotations

from .catalog import Catalog
from .config import Config
from .store import validate_snapshot_name


def initialize(config: Config, baseline: str = "initial") -> None:
    """Register an existing baseline without cloning or changing VM artifacts."""

    validate_snapshot_name(baseline)
    config.ensure_data_directories()
    Catalog(config).initialize_baseline(baseline)
