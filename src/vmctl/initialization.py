"""Guided import and fresh-install transactions for an unconfigured vmctl."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import TextIO

from .catalog import Catalog
from .config import CONFIG_SCHEMA_VERSION, Config
from .errors import ArtifactError, StateConflictError, TransactionError, UsageError
from .network import ensure_network_identity
from .store import (
    DeletionCategory,
    FileLock,
    atomic_write_json,
    bundle_state,
    clone_bundle,
    permanent_delete_tree,
    validate_bundle,
    validate_snapshot_name,
)


def _option(arguments: list[str], name: str, default: str | None = None) -> str | None:
    if name not in arguments:
        return default
    index = arguments.index(name)
    if index + 1 >= len(arguments):
        raise UsageError(f"Missing value for {name}")
    return arguments[index + 1]


def _flag(arguments: list[str], name: str) -> bool:
    return name in arguments


def _require_confirmation(arguments: list[str], summary: str) -> None:
    if _flag(arguments, "--yes"):
        return
    raise StateConflictError(
        summary,
        hint="Review the paths above, then rerun with --yes.",
    )


def _write_installed_config(config: Config) -> None:
    path = config.config_file
    if path is None:
        raise TransactionError("No installed configuration path is available.")
    atomic_write_json(
        path,
        {
            "schemaVersion": CONFIG_SCHEMA_VERSION,
            "liveBundle": str(config.live_bundle),
            "snapshotDirectory": str(config.snapshot_dir),
            "recoveryDirectory": str(config.recovery_dir),
            "stateDirectory": str(config.state_dir),
            "runnerApplication": str(config.app_bundle),
            "launcher": str(config.launcher_path),
        },
    )


def _assert_uninitialized(config: Config) -> None:
    if config.base_file.exists() or config.live_file.exists():
        raise StateConflictError("vmctl is already initialized.")
    if config.live_bundle.exists() or config.live_bundle.is_symlink():
        raise StateConflictError(
            f"Initialization destination already exists: {config.live_bundle}"
        )


def _create_initial_base(config: Config, name: str) -> None:
    catalog = Catalog(config)
    snapshot_directory = catalog.snapshot_directory(name)
    if snapshot_directory.exists() or snapshot_directory.is_symlink():
        raise StateConflictError(f"Initial snapshot already exists: {name}")
    temporary = config.snapshot_dir / f".init-{uuid.uuid4().hex}"
    try:
        clone_bundle(config.live_bundle, temporary / "VM.bundle")
        catalog.write_snapshot_metadata(
            temporary,
            name=name,
            parent=None,
            captured_state=bundle_state(config.live_bundle),
        )
        os.replace(temporary, snapshot_directory)
        catalog.set_base(name)
        catalog.set_live_origin(name)
    except Exception:
        if temporary.exists() and not temporary.is_symlink():
            permanent_delete_tree(
                temporary,
                expected_root=config.snapshot_dir,
                category=DeletionCategory.SNAPSHOT,
                live_bundle=config.live_bundle,
            )
        raise


def _private_bundle(bundle: Path) -> None:
    bundle.chmod(0o700)
    for child in bundle.iterdir():
        if child.is_symlink():
            raise ArtifactError(f"VM bundle contains a symlink: {child}")
        if child.is_file():
            child.chmod(0o600)


def _rollback_initial_catalog(
    config: Config,
    *,
    base: str,
    delete_live: bool,
) -> None:
    for metadata in (config.live_file, config.base_file):
        if metadata.exists() and not metadata.is_symlink():
            metadata.unlink()
    snapshot = config.snapshot_dir / base
    if snapshot.exists() and not snapshot.is_symlink():
        permanent_delete_tree(
            snapshot,
            expected_root=config.snapshot_dir,
            category=DeletionCategory.SNAPSHOT,
            live_bundle=config.live_bundle,
        )
    if delete_live and config.live_bundle.exists() and not config.live_bundle.is_symlink():
        permanent_delete_tree(
            config.live_bundle,
            expected_root=config.live_bundle.parent,
            category=DeletionCategory.TRANSACTION_TEMPORARY,
            live_bundle=Path("/nonexistent-vmctl-live"),
        )


def _apply_import(
    config: Config,
    *,
    source: Path,
    destination: Path,
    mode: str,
    base: str,
    discard_saved_state: bool,
) -> None:
    effective = dataclasses.replace(config, live_bundle=destination)
    staged = config.live_bundle.parent / f".vmctl-init-{uuid.uuid4().hex}"
    activated = False
    with FileLock(config.lock_file):
        _assert_uninitialized(config)
        effective.ensure_data_directories()
        try:
            if mode == "clone":
                config.live_bundle.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                clone_bundle(source, staged)
                if discard_saved_state:
                    (staged / "SaveFile.vzvmsave").unlink(missing_ok=True)
                ensure_network_identity(staged, generate=True, replace=True)
                _private_bundle(staged)
                os.replace(staged, config.live_bundle)
                activated = True
            else:
                ensure_network_identity(source)
                _private_bundle(source)
            validate_bundle(effective.live_bundle)
            _create_initial_base(effective, base)
            _write_installed_config(effective)
        except Exception:
            if staged.exists() and not staged.is_symlink():
                permanent_delete_tree(
                    staged,
                    expected_root=config.live_bundle.parent,
                    category=DeletionCategory.TRANSACTION_TEMPORARY,
                    live_bundle=config.live_bundle,
                )
            _rollback_initial_catalog(
                effective,
                base=base,
                delete_live=activated,
            )
            raise


def import_bundle(
    config: Config,
    arguments: list[str],
    *,
    stdout: TextIO,
) -> None:
    if not arguments:
        raise UsageError(
            "Usage: vmctl init import PATH [--mode clone|adopt] [--base NAME] "
            "[--discard-saved-state] [--yes]"
        )
    source = Path(arguments[0]).expanduser().resolve()
    mode = _option(arguments, "--mode", "clone")
    base = validate_snapshot_name(_option(arguments, "--base", "initial") or "initial")
    discard_saved_state = _flag(arguments, "--discard-saved-state")
    if mode not in {"clone", "adopt"}:
        raise UsageError("Import mode must be clone or adopt.")
    if mode == "adopt" and discard_saved_state:
        raise UsageError("--discard-saved-state is available only with clone import.")
    validate_bundle(source)
    saved_state = source / "SaveFile.vzvmsave"
    if saved_state.exists() and not discard_saved_state:
        raise StateConflictError(
            "The source bundle contains suspended state that may not restore with "
            "a newly built runner.",
            hint=(
                "Shut down the source VM before importing it. To cold boot an "
                "independent clone instead, rerun with --mode clone "
                "--discard-saved-state and review the plan."
            ),
        )
    _assert_uninitialized(config)
    destination = source if mode == "adopt" else config.live_bundle
    stdout.write(
        f"Import source: {source}\n"
        f"Mode: {mode}\n"
        f"Saved state: {'discard from clone' if discard_saved_state else 'none'}\n"
        f"Managed live bundle: {destination}\n"
        f"Initial base: {base}\n"
    )
    _require_confirmation(arguments, "Import is ready but has not changed any files.")

    _apply_import(
        config,
        source=source,
        destination=destination,
        mode=mode,
        base=base,
        discard_saved_state=discard_saved_state,
    )
    stdout.write(f"Initialized vmctl from existing bundle. Base: {base}\n")


def _run_installer(config: Config, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    helper = config.app_bundle / "Contents" / "Helpers" / "VMInstaller"
    if helper.is_symlink() or not helper.is_file():
        raise ArtifactError(f"VM installer helper is missing: {helper}")
    return subprocess.run(
        [str(helper), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def _latest_record(config: Config) -> dict[str, object]:
    result = _run_installer(config, ["inspect", "--restore", "latest"])
    if result.returncode != 0:
        raise TransactionError(result.stderr.strip() or "Could not query Apple's restore image.")
    try:
        value = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise TransactionError("Installer helper returned invalid restore metadata.") from error
    if not isinstance(value, dict) or not isinstance(value.get("source"), str):
        raise TransactionError("Installer helper returned incomplete restore metadata.")
    return value


def _activate_install(
    config: Config,
    *,
    local_restore: Path,
    disk_gib: int,
    base: str,
    stdout: TextIO,
) -> None:
    with FileLock(config.lock_file):
        _assert_uninitialized(config)
        config.ensure_data_directories()
        config.live_bundle.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        staged = config.live_bundle.parent / f".vmctl-install-{uuid.uuid4().hex}"
        activated = False
        try:
            result = _run_installer(
                config,
                [
                    "install",
                    "--restore",
                    str(local_restore),
                    "--bundle",
                    str(staged),
                    "--disk-size-gib",
                    str(disk_gib),
                ],
            )
            if result.stdout:
                stdout.write(result.stdout)
            if result.returncode != 0:
                raise TransactionError(
                    result.stderr.strip() or "macOS installation failed."
                )
            validate_bundle(staged)
            _private_bundle(staged)
            os.replace(staged, config.live_bundle)
            activated = True
            _create_initial_base(config, base)
            _write_installed_config(config)
        except Exception:
            if staged.exists() and not staged.is_symlink():
                permanent_delete_tree(
                    staged,
                    expected_root=config.live_bundle.parent,
                    category=DeletionCategory.TRANSACTION_TEMPORARY,
                    live_bundle=config.live_bundle,
                )
            _rollback_initial_catalog(
                config,
                base=base,
                delete_live=activated,
            )
            raise


def install_bundle(
    config: Config,
    arguments: list[str],
    *,
    stdout: TextIO,
) -> None:
    restore = _option(arguments, "--restore", "latest") or "latest"
    base = validate_snapshot_name(_option(arguments, "--base", "initial") or "initial")
    disk_size = _option(arguments, "--disk-size-gib", "128") or "128"
    try:
        disk_gib = int(disk_size)
    except ValueError as error:
        raise UsageError("Disk size must be an integer number of GiB.") from error
    if disk_gib < 64:
        raise UsageError("Disk size must be at least 64 GiB.")
    _assert_uninitialized(config)
    home = config.config_file.parents[3] if config.config_file is not None else Path.home()
    cache = (
        home
        / "Library"
        / "Caches"
        / "vmctl"
        / "restore-images"
    )
    local_restore: Path
    source_description: str
    if restore == "latest":
        record = _latest_record(config)
        source_description = str(record["source"])
        local_restore = cache / Path(
            urllib.parse.urlparse(source_description).path
        ).name
        if not local_restore.name:
            local_restore = cache / "RestoreImage.ipsw"
    else:
        local_restore = Path(restore).expanduser().resolve()
        source_description = str(local_restore)
        if not local_restore.is_file():
            raise ArtifactError(f"Restore image does not exist: {local_restore}")

    storage_probe = config.live_bundle.parent
    while not storage_probe.exists() and storage_probe != storage_probe.parent:
        storage_probe = storage_probe.parent
    free = shutil.disk_usage(storage_probe).free
    required = 25 * 1024**3
    stdout.write(
        f"Restore source: {source_description}\n"
        f"Restore cache: {local_restore}\n"
        f"VM destination: {config.live_bundle}\n"
        f"Disk allocation: {disk_gib} GiB sparse\n"
        f"Minimum working free space: {required / 1024**3:.0f} GiB\n"
        f"Available: {free / 1024**3:.1f} GiB\n"
    )
    if free < required:
        raise StateConflictError("Insufficient free space for macOS installation.")
    _require_confirmation(arguments, "Installation is ready but no download has started.")

    if restore == "latest" and not local_restore.is_file():
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        cache.chmod(0o700)
        partial = local_restore.with_suffix(local_restore.suffix + ".partial")
        request = urllib.request.Request(source_description, method="GET")
        try:
            with urllib.request.urlopen(request) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output)
            os.replace(partial, local_restore)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    _activate_install(
        config,
        local_restore=local_restore,
        disk_gib=disk_gib,
        base=base,
        stdout=stdout,
    )
    if restore == "latest" and not _flag(arguments, "--keep-restore-image"):
        local_restore.unlink(missing_ok=True)
    stdout.write(f"Installed and initialized macOS VM. Base: {base}\n")


def render_init_help(stdout: TextIO) -> None:
    stdout.write(
        "Initialize vmctl:\n"
        "  vmctl init import PATH [--mode clone|adopt] [--base NAME] "
        "[--discard-saved-state] [--yes]\n"
        "  vmctl init install [--restore latest|PATH] [--disk-size-gib N] "
        "[--base NAME] [--keep-restore-image] [--yes]\n"
        "\nClone import is recommended because it leaves the source bundle unchanged. "
        "Shut down the source VM before import. If a suspended source cannot be "
        "shut down, clone import can explicitly discard only the clone's saved "
        "state with --discard-saved-state.\n"
    )
