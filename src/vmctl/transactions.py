"""Journaled reconciliation for interrupted live-VM replacement operations."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .config import Config
from .errors import ArtifactError, StateConflictError, TransactionError
from .store import (
    DeletionCategory,
    atomic_write_json,
    path_timestamp,
    permanent_delete_tree,
    read_json,
    validate_bundle,
)


TRANSACTION_PHASES = ("prepared", "displaced", "activated", "committed")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def read_transaction(config: Config) -> dict[str, Any] | None:
    if not config.transaction_file.exists():
        return None
    return read_json(config.transaction_file)


def begin_transaction(
    config: Config,
    *,
    identifier: str,
    operation: str,
    source_snapshot: str,
    temporary_live: Path,
    rollback_bundle: Path,
    previous_live_origin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if config.transaction_file.exists():
        raise StateConflictError(
            f"An unfinished vmctl transaction already exists: {config.transaction_file}"
        )
    journal: dict[str, Any] = {
        "schemaVersion": 1,
        "id": identifier,
        "operation": operation,
        "sourceSnapshot": source_snapshot,
        "temporaryLive": str(temporary_live),
        "rollbackBundle": str(rollback_bundle),
        "previousLiveOrigin": previous_live_origin,
        "phase": "prepared",
        "startedAt": path_timestamp(),
    }
    atomic_write_json(config.transaction_file, journal)
    return journal


def set_transaction_phase(config: Config, phase: str) -> dict[str, Any]:
    if phase not in TRANSACTION_PHASES:
        raise TransactionError(f"Invalid transaction phase: {phase}")
    journal = read_transaction(config)
    if journal is None:
        raise ArtifactError(f"Transaction journal does not exist: {config.transaction_file}")
    current = journal.get("phase")
    if current not in TRANSACTION_PHASES:
        raise TransactionError(f"Transaction journal has invalid phase: {current!r}")
    if TRANSACTION_PHASES.index(phase) < TRANSACTION_PHASES.index(str(current)):
        raise TransactionError(
            f"Transaction phase cannot move backward from {current} to {phase}"
        )
    journal["phase"] = phase
    atomic_write_json(config.transaction_file, journal)
    return journal


def _journal_paths(
    config: Config, journal: dict[str, Any]
) -> tuple[str, str, str, Path, Path, Path]:
    identifier = journal.get("id")
    operation = journal.get("operation")
    source = journal.get("sourceSnapshot")
    phase = journal.get("phase")
    temporary_text = journal.get("temporaryLive")
    rollback_text = journal.get("rollbackBundle")
    if not isinstance(identifier, str) or not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise TransactionError("Transaction journal has an invalid identifier")
    if operation not in {"load", "reset"}:
        raise TransactionError(f"Transaction journal has invalid operation: {operation!r}")
    if not isinstance(source, str) or not source:
        raise TransactionError("Transaction journal has no source snapshot")
    if phase not in TRANSACTION_PHASES:
        raise TransactionError(f"Transaction journal has invalid phase: {phase!r}")
    if not isinstance(temporary_text, str) or not isinstance(rollback_text, str):
        raise TransactionError("Transaction journal has invalid paths")

    temporary = Path(temporary_text)
    rollback = Path(rollback_text)
    transaction_directory = config.recovery_dir / "pending" / identifier
    expected_temporary = config.live_bundle.parent / (
        f".{config.live_bundle.name}.vmctl-{identifier}"
    )
    expected_rollback = transaction_directory / "VM.bundle"
    if temporary.resolve(strict=False) != expected_temporary.resolve(strict=False):
        raise TransactionError(
            f"Transaction temporary path is outside its exact location: {temporary}"
        )
    if rollback.resolve(strict=False) != expected_rollback.resolve(strict=False):
        raise TransactionError(
            f"Transaction rollback path is outside its exact location: {rollback}"
        )
    return identifier, str(operation), source, temporary, rollback, transaction_directory


def _delete_temporary(config: Config, temporary: Path) -> None:
    if temporary.exists() or temporary.is_symlink():
        permanent_delete_tree(
            temporary,
            expected_root=config.live_bundle.parent,
            category=DeletionCategory.TRANSACTION_TEMPORARY,
            live_bundle=config.live_bundle,
        )


def _delete_pending(config: Config, transaction_directory: Path) -> None:
    if transaction_directory.exists() or transaction_directory.is_symlink():
        permanent_delete_tree(
            transaction_directory,
            expected_root=config.recovery_dir / "pending",
            category=DeletionCategory.TRANSACTION_TEMPORARY,
            live_bundle=config.live_bundle,
        )


def _clear_journal(config: Config) -> None:
    try:
        config.transaction_file.unlink()
    except FileNotFoundError:
        return
    directory_fd = os.open(config.transaction_file.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _quarantine_failure(
    config: Config,
    journal: dict[str, Any],
    error: Exception,
    *,
    identifier: str | None,
    transaction_directory: Path | None,
) -> Path:
    failed_root = config.recovery_dir / "failed"
    failed_root.mkdir(parents=True, exist_ok=True)
    safe_identifier = identifier if identifier and _IDENTIFIER_PATTERN.fullmatch(identifier) else "invalid"
    failed_directory = failed_root / (
        f"{path_timestamp()}--transaction-{safe_identifier}"
    )
    if (
        transaction_directory is not None
        and transaction_directory.exists()
        and not transaction_directory.is_symlink()
        and transaction_directory.parent.resolve(strict=False)
        == (config.recovery_dir / "pending").resolve(strict=False)
    ):
        os.replace(transaction_directory, failed_directory)
    else:
        failed_directory.mkdir()
    atomic_write_json(
        failed_directory / "failure.json",
        {
            "schemaVersion": 1,
            "error": str(error),
            "journal": journal,
        },
    )
    if config.transaction_file.exists():
        os.replace(config.transaction_file, failed_directory / "transaction.json")
    return failed_directory


def _rollback_uncommitted(
    config: Config,
    catalog: Catalog,
    journal: dict[str, Any],
    temporary: Path,
    rollback: Path,
    transaction_directory: Path,
) -> None:
    validate_bundle(rollback)
    if config.live_bundle.exists():
        if temporary.exists() or temporary.is_symlink():
            raise TransactionError(
                "Cannot reconcile transaction because live and temporary bundles both exist"
            )
        os.replace(config.live_bundle, temporary)
    os.replace(rollback, config.live_bundle)
    validate_bundle(config.live_bundle)
    previous_origin = journal.get("previousLiveOrigin")
    if isinstance(previous_origin, dict):
        atomic_write_json(config.live_file, previous_origin)
    _delete_temporary(config, temporary)
    _delete_pending(config, transaction_directory)
    _clear_journal(config)


def reconcile_transaction(
    config: Config,
    catalog: Catalog,
    *,
    vm_running: bool = False,
) -> str | None:
    """Reconcile one journal, returning the completed recovery action."""

    journal = read_transaction(config)
    if journal is None:
        return None
    if vm_running:
        raise StateConflictError(
            "An unfinished VM transaction requires reconciliation while the VM is stopped.",
            hint="Run vmctl stop, then retry.",
        )

    identifier: str | None = None
    transaction_directory: Path | None = None
    try:
        (
            identifier,
            _operation,
            source,
            temporary,
            rollback,
            transaction_directory,
        ) = _journal_paths(config, journal)
        phase = str(journal["phase"])

        if phase == "committed":
            validate_bundle(config.live_bundle)
            origin = catalog.live_origin()
            if origin.get("sourceSnapshot") != source or origin.get("detached"):
                raise TransactionError(
                    "Committed transaction live-origin metadata does not match its source"
                )
            _delete_temporary(config, temporary)
            _delete_pending(config, transaction_directory)
            _clear_journal(config)
            return "committed-cleanup"

        if rollback.exists():
            _rollback_uncommitted(
                config,
                catalog,
                journal,
                temporary,
                rollback,
                transaction_directory,
            )
            return "rolled-back"

        if phase != "prepared" or not config.live_bundle.exists():
            raise TransactionError(
                f"Cannot restore uncommitted {phase} transaction; rollback bundle is missing"
            )
        validate_bundle(config.live_bundle)
        _delete_temporary(config, temporary)
        _delete_pending(config, transaction_directory)
        _clear_journal(config)
        return "rolled-back"
    except StateConflictError:
        raise
    except Exception as error:
        failed = _quarantine_failure(
            config,
            journal,
            error,
            identifier=identifier,
            transaction_directory=transaction_directory,
        )
        raise TransactionError(
            f"Could not safely reconcile transaction; preserved diagnostics at {failed}: {error}"
        ) from error
