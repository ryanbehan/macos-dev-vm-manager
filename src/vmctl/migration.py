"""Inventory-first migration for legacy recovery/live and recovery/removed data."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import dataclasses
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .config import Config
from .errors import ArtifactError, StateConflictError, TransactionError
from .store import (
    DeletionCategory,
    atomic_write_json,
    permanent_delete_tree,
    read_private_json,
    validate_bundle,
)
from .transactions import read_transaction


LEGACY_CATEGORIES = ("live", "removed")
MIGRATION_SCHEMA_VERSION = 1


def _logical_size(path: Path) -> int:
    try:
        total = path.lstat().st_size
    except FileNotFoundError:
        return 0
    if path.is_symlink() or not path.is_dir():
        return total
    for child in path.iterdir():
        total += _logical_size(child)
    return total


def candidate_digest(candidates: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        candidates,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def inventory_legacy_recovery(config: Config) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for category in LEGACY_CATEGORIES:
        root = config.recovery_dir / category
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            candidates.append(
                {
                    "category": category,
                    "path": os.path.abspath(path),
                    "logicalBytes": _logical_size(path),
                    "isSymlink": path.is_symlink(),
                }
            )
    candidates.sort(key=lambda item: (str(item["category"]), str(item["path"])))

    storage_probe = config.recovery_dir
    while not storage_probe.exists() and storage_probe != storage_probe.parent:
        storage_probe = storage_probe.parent
    free = shutil.disk_usage(storage_probe).free
    return {
        "schemaVersion": 1,
        "recoveryRoot": str(config.recovery_dir.resolve(strict=False)),
        "entryCount": len(candidates),
        "logicalBytes": sum(int(candidate["logicalBytes"]) for candidate in candidates),
        "diskFreeBytes": free,
        "candidates": candidates,
        "candidateDigest": candidate_digest(candidates),
    }


def write_inventory_manifest(path: Path, inventory: dict[str, Any]) -> None:
    atomic_write_json(path, inventory)


def _validate_candidate_path(config: Config, candidate: dict[str, Any]) -> tuple[Path, Path]:
    category = candidate.get("category")
    path_text = candidate.get("path")
    if category not in LEGACY_CATEGORIES or not isinstance(path_text, str):
        raise TransactionError(f"Legacy manifest contains an invalid candidate: {candidate!r}")
    expected_root = config.recovery_dir / str(category)
    target = Path(path_text)
    if Path(os.path.abspath(target)).parent != Path(os.path.abspath(expected_root)):
        raise TransactionError(
            f"Legacy candidate is outside exact {category} root {expected_root}: {target}"
        )
    if target.is_symlink() or bool(candidate.get("isSymlink")):
        raise TransactionError(f"Legacy candidate is a symlink and cannot be deleted: {target}")
    if not target.is_dir():
        raise TransactionError(f"Legacy candidate is not a directory: {target}")
    return target, expected_root


def execute_legacy_recovery(
    config: Config,
    manifest_path: Path,
    *,
    approved_digest: str,
    vm_running: bool = False,
) -> dict[str, Any]:
    if vm_running:
        raise StateConflictError(
            "Legacy recovery cleanup requires the VM runner to be stopped."
        )
    manifest = read_private_json(manifest_path)
    if manifest.get("recoveryRoot") != str(config.recovery_dir.resolve(strict=False)):
        raise TransactionError(
            "Legacy recovery manifest was generated for a different recovery root"
        )
    candidates = manifest.get("candidates")
    digest = manifest.get("candidateDigest")
    if not isinstance(candidates, list) or not isinstance(digest, str):
        raise TransactionError(f"Legacy recovery manifest is invalid: {manifest_path}")
    if candidate_digest(candidates) != digest:
        raise TransactionError("Legacy recovery manifest content does not match its digest")
    if approved_digest != digest:
        raise TransactionError(
            "Legacy recovery execution requires the explicitly reviewed candidate digest"
        )

    current = inventory_legacy_recovery(config)
    if current["candidateDigest"] != digest:
        raise TransactionError(
            "Legacy recovery candidates changed after review; generate and review a new manifest"
        )

    validated = [
        (*_validate_candidate_path(config, candidate), candidate)
        for candidate in candidates
    ]
    before = shutil.disk_usage(config.recovery_dir).free
    for target, expected_root, _candidate in validated:
        permanent_delete_tree(
            target,
            expected_root=expected_root,
            category=DeletionCategory.LEGACY_RECOVERY,
            live_bundle=config.live_bundle,
        )
    after = shutil.disk_usage(config.recovery_dir).free
    return {
        "schemaVersion": 1,
        "deletedEntries": len(validated),
        "logicalBytesReported": int(manifest.get("logicalBytes", 0)),
        "diskFreeBytesBefore": before,
        "diskFreeBytesAfter": after,
        "candidateDigest": digest,
    }


def _migration_digest(plan: dict[str, Any]) -> str:
    canonical = {
        key: value
        for key, value in plan.items()
        if key not in {"candidateDigest", "manifestPath"}
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def create_migration_plan(
    config: Config,
    *,
    legacy_root: Path | None = None,
) -> dict[str, Any]:
    """Create a deterministic, read-only plan that adopts existing data in place."""

    source = config
    if legacy_root is not None:
        root = legacy_root.resolve()
        home = (
            config.config_file.parents[3]
            if config.config_file is not None and len(config.config_file.parents) >= 4
            else Path.home()
        )
        legacy_live = (
            config.live_bundle
            if config.live_bundle.exists() or config.live_bundle.is_symlink()
            else home / "VM.bundle"
        )
        source = dataclasses.replace(
            config,
            live_bundle=legacy_live,
            snapshot_dir=root / "snapshots",
            recovery_dir=root / "recovery",
            state_dir=root / "state",
        )
    validate_bundle(source.live_bundle)
    for path in (source.snapshot_dir, source.recovery_dir, source.state_dir):
        if path.is_symlink():
            raise TransactionError(f"Migration source root must not be a symlink: {path}")
    catalog = Catalog(source)
    base = catalog.get_base()
    catalog.get(base)
    transaction = read_transaction(source)
    plan: dict[str, Any] = {
        "schemaVersion": MIGRATION_SCHEMA_VERSION,
        "operation": "adopt-existing-data",
        "programSource": str(source.project_root.resolve(strict=False)),
        "liveBundle": str(source.live_bundle.resolve(strict=False)),
        "snapshotDirectory": str(source.snapshot_dir.resolve(strict=False)),
        "recoveryDirectory": str(source.recovery_dir.resolve(strict=False)),
        "stateDirectory": str(source.state_dir.resolve(strict=False)),
        "runnerApplication": os.path.abspath(config.app_bundle),
        "launcher": os.path.abspath(config.launcher_path),
        "configuration": (
            os.path.abspath(config.config_file) if config.config_file else None
        ),
        "baseSnapshot": base,
        "dataMovement": "none",
        "deletions": [],
        "expectedWrites": (
            [str(config.config_file)] if config.config_file is not None else []
        ),
        "logicalBytesRequired": 0,
        "pendingTransaction": transaction is not None,
    }
    plan["candidateDigest"] = _migration_digest(plan)
    return plan


def render_migration_plan(plan: dict[str, Any], manifest_path: Path) -> str:
    return (
        "Migration plan (read-only; no data will move or be deleted):\n"
        f"  Live VM: {plan['liveBundle']}\n"
        f"  Snapshots: {plan['snapshotDirectory']}\n"
        f"  Recovery: {plan['recoveryDirectory']}\n"
        f"  State: {plan['stateDirectory']}\n"
        f"  New program: {plan['runnerApplication']}\n"
        f"  Configuration write: {plan['configuration']}\n"
        f"  Required additional storage: {plan['logicalBytesRequired']} bytes\n"
        f"  Manifest: {manifest_path}\n"
        f"  Approval digest: {plan['candidateDigest']}\n"
        "Apply only after review:\n"
        f"  vmctl migrate apply --manifest {manifest_path} "
        f"--approve-digest {plan['candidateDigest']}\n"
    )


def apply_migration_plan(
    config: Config,
    manifest_path: Path,
    *,
    approved_digest: str,
    vm_running: bool,
) -> dict[str, Any]:
    """Adopt existing data paths by writing only the installed configuration."""

    if vm_running:
        raise StateConflictError("Migration requires the VM runner to be stopped.")
    manifest = read_private_json(manifest_path)
    if manifest.get("schemaVersion") != MIGRATION_SCHEMA_VERSION:
        raise TransactionError("Migration manifest schema is unsupported.")
    digest = manifest.get("candidateDigest")
    if not isinstance(digest, str) or _migration_digest(manifest) != digest:
        raise TransactionError("Migration manifest content does not match its digest.")
    if approved_digest != digest:
        raise TransactionError("Migration requires the explicitly reviewed digest.")
    if manifest.get("pendingTransaction"):
        raise StateConflictError("Migration cannot apply with a pending transaction.")
    if manifest.get("dataMovement") != "none" or manifest.get("deletions") != []:
        raise TransactionError("This release accepts only no-move, no-delete migrations.")

    source = dataclasses.replace(
        config,
        live_bundle=Path(str(manifest["liveBundle"])).resolve(),
        snapshot_dir=Path(str(manifest["snapshotDirectory"])).resolve(),
        recovery_dir=Path(str(manifest["recoveryDirectory"])).resolve(),
        state_dir=Path(str(manifest["stateDirectory"])).resolve(),
    )
    current = create_migration_plan(source)
    comparable = {
        key: current.get(key)
        for key in (
            "liveBundle",
            "snapshotDirectory",
            "recoveryDirectory",
            "stateDirectory",
            "baseSnapshot",
            "pendingTransaction",
        )
    }
    expected = {key: manifest.get(key) for key in comparable}
    if comparable != expected:
        raise TransactionError(
            "Migration source changed after review; generate and review a new plan."
        )
    if config.config_file is None:
        raise ArtifactError("No installed configuration path is available.")
    atomic_write_json(
        config.config_file,
        {
            "schemaVersion": 1,
            "liveBundle": str(source.live_bundle),
            "snapshotDirectory": str(source.snapshot_dir),
            "recoveryDirectory": str(source.recovery_dir),
            "stateDirectory": str(source.state_dir),
            "runnerApplication": str(config.app_bundle),
            "launcher": str(config.launcher_path),
        },
    )
    return {
        "schemaVersion": 1,
        "configuration": str(config.config_file),
        "candidateDigest": digest,
        "dataMovement": "none",
        "deletions": [],
    }
