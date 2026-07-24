"""Safe filesystem primitives for VM bundles and metadata."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import AbstractContextManager
from datetime import datetime
from enum import Enum
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .errors import ArtifactError, StateConflictError, TransactionError, UsageError


REQUIRED_VM_ARTIFACTS = (
    "Disk.img",
    "AuxiliaryStorage",
    "HardwareModel",
    "MachineIdentifier",
)
SNAPSHOT_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,78}[A-Za-z0-9])?$"
)
RESERVED_SNAPSHOT_NAMES = {".", "..", "live", "removed", "failed", "state"}


class DeletionCategory(str, Enum):
    """The narrowly scoped tree types that vmctl is allowed to delete."""

    SNAPSHOT = "snapshot"
    TRANSACTION_TEMPORARY = "transaction-temporary"
    LEGACY_RECOVERY = "legacy-recovery"
    PROGRAM_RELEASES = "program-releases"
    DATA_PURGE = "data-purge"


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def path_timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S.%f%z")


def validate_snapshot_name(name: str) -> str:
    if name in RESERVED_SNAPSHOT_NAMES or not SNAPSHOT_NAME_PATTERN.fullmatch(name):
        raise UsageError(
            f"Invalid snapshot name: {name!r}",
            hint="Use 1-80 ASCII letters, numbers, periods, underscores, or hyphens; begin and end with a letter or number.",
        )
    return name


def validate_bundle(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ArtifactError(f"VM bundle does not exist: {path}")
    missing: list[str] = []
    for name in REQUIRED_VM_ARTIFACTS:
        artifact = path / name
        try:
            metadata = artifact.lstat()
        except FileNotFoundError:
            missing.append(name)
            continue
        if metadata.st_uid != os.geteuid():
            raise ArtifactError(f"VM artifact is owned by another user: {artifact}")
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size == 0
        ):
            missing.append(name)
    if missing:
        raise ArtifactError(
            f"VM bundle is incomplete: {path}; missing or empty: {', '.join(missing)}"
        )
    network_identity = path / "NetworkMACAddress"
    if network_identity.exists() or network_identity.is_symlink():
        identity_metadata = network_identity.lstat()
        if (
            network_identity.is_symlink()
            or not stat.S_ISREG(identity_metadata.st_mode)
            or identity_metadata.st_uid != os.geteuid()
        ):
            raise ArtifactError(
                f"VM network identity must be a regular file: {network_identity}"
            )
        value = network_identity.read_text(encoding="ascii").strip()
        parts = value.split(":")
        try:
            octets = [int(part, 16) for part in parts]
        except ValueError as error:
            raise ArtifactError(f"VM network identity is invalid: {network_identity}") from error
        if (
            len(parts) != 6
            or any(len(part) != 2 for part in parts)
            or any(octet < 0 or octet > 255 for octet in octets)
            or octets[0] & 0x01
            or not octets[0] & 0x02
        ):
            raise ArtifactError(f"VM network identity is invalid: {network_identity}")


def bundle_state(path: Path) -> str:
    validate_bundle(path)
    save_file = path / "SaveFile.vzvmsave"
    return "suspended" if save_file.is_file() and save_file.stat().st_size > 0 else "shutdown"


def atomic_write_json(path: Path, value: Any) -> None:
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not parent_existed:
        os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ArtifactError(f"Metadata file must not be a symlink: {path}")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise ArtifactError(f"Metadata file must be a current-user regular file: {path}")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            value = json.load(handle)
    except FileNotFoundError as error:
        raise ArtifactError(f"Metadata file does not exist: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactError(f"Metadata file is invalid: {path}: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise ArtifactError(f"Metadata file must contain an object: {path}")
    return value


def read_private_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ArtifactError(f"Metadata file does not exist: {path}") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ArtifactError(
            f"Sensitive metadata must be a private current-user regular file: {path}"
        )
    return read_json(path)


class FileLock(AbstractContextManager["FileLock"]):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise StateConflictError(f"Refusing symlinked lock file: {self.path}")
        self._handle = self.path.open("a+")
        os.chmod(self.path, 0o600)
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self._handle.close()
            self._handle = None
            raise StateConflictError(
                "Another mutating vmctl command is already running."
            ) from error
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def clone_bundle(
    source: Path,
    destination: Path,
    *,
    runner: CommandRunner = subprocess.run,
) -> None:
    validate_bundle(source)
    if destination.exists() or destination.is_symlink():
        raise TransactionError(f"Clone destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = runner(
        ["/bin/cp", "-a", "-c", str(source), str(destination)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown cp error"
        raise TransactionError(
            f"Failed to clone {source} to {destination}: {detail}"
        )
    validate_bundle(destination)


def move_path(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.exists():
        raise ArtifactError(f"Path does not exist: {source}")
    if destination.exists() or destination.is_symlink():
        raise TransactionError(f"Recovery destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, destination)
    except OSError as error:
        raise TransactionError(
            f"Failed to move {source} to {destination}: {error}"
        ) from error


def permanent_delete_tree(
    target: Path,
    *,
    expected_root: Path,
    category: DeletionCategory,
    live_bundle: Path,
    protected_paths: tuple[Path, ...] = (),
) -> None:
    """Permanently delete one validated direct child of an expected root.

    Callers must select a supported category and the narrowest root that owns
    the target. The direct-child rule lets the same primitive safely serve
    snapshot, transaction-temporary, and reviewed legacy-recovery deletion
    without exposing an unrestricted recursive-delete operation.
    """

    if not isinstance(category, DeletionCategory):
        raise TransactionError(f"Unsupported permanent-deletion category: {category!r}")

    target = Path(target)
    expected_root = Path(expected_root)

    if expected_root.is_symlink():
        raise TransactionError(
            f"Refusing permanent {category.value} deletion through symlink root: {expected_root}"
        )
    try:
        resolved_root = expected_root.resolve(strict=True)
    except FileNotFoundError as error:
        raise ArtifactError(f"Deletion root does not exist: {expected_root}") from error
    if not resolved_root.is_dir():
        raise ArtifactError(f"Deletion root is not a directory: {expected_root}")

    absolute_root = Path(os.path.abspath(expected_root))
    absolute_target = Path(os.path.abspath(target))
    if absolute_target == absolute_root:
        raise TransactionError(f"Refusing to delete the deletion root: {expected_root}")
    if absolute_target.parent != absolute_root:
        raise TransactionError(
            f"Refusing permanent {category.value} deletion outside exact root {expected_root}: {target}"
        )
    if target.is_symlink():
        raise TransactionError(
            f"Refusing permanent {category.value} deletion of symlink: {target}"
        )
    try:
        resolved_target = target.resolve(strict=True)
    except FileNotFoundError as error:
        raise ArtifactError(f"Deletion target does not exist: {target}") from error
    if not resolved_target.is_dir():
        raise ArtifactError(f"Deletion target is not a directory: {target}")
    if resolved_target.parent != resolved_root:
        raise TransactionError(
            f"Refusing permanent {category.value} deletion outside resolved root {resolved_root}: {target}"
        )

    def paths_overlap(first: Path, second: Path) -> bool:
        return (
            first == second
            or first in second.parents
            or second in first.parents
        )

    resolved_live = Path(live_bundle).resolve(strict=False)
    if paths_overlap(resolved_target, resolved_live) and category is not DeletionCategory.DATA_PURGE:
        raise StateConflictError(
            f"Refusing to permanently delete the live VM or its containing path: {target}"
        )

    for protected in protected_paths:
        resolved_protected = Path(protected).resolve(strict=False)
        if paths_overlap(resolved_target, resolved_protected):
            raise StateConflictError(
                f"Refusing to permanently delete protected path {protected}: {target}"
            )

    try:
        shutil.rmtree(resolved_target)
    except OSError as error:
        raise TransactionError(
            f"Failed to permanently delete {category.value} tree {target}: {error}"
        ) from error
