"""Manifest-bounded program uninstall with separately approved data purge."""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .errors import ArtifactError, StateConflictError, UsageError
from .store import DeletionCategory, permanent_delete_tree, read_private_json


def _install_root(config: Config) -> Path:
    if config.config_file is None:
        raise ArtifactError("Installed configuration path is unavailable.")
    return config.config_file.parent.resolve(strict=False)


def _unlink_owned_symlink(path: Path, expected_parent: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.parent.resolve(strict=False) != expected_parent.resolve(strict=False):
        raise StateConflictError(f"Refusing to remove path outside its owned parent: {path}")
    if not path.is_symlink():
        raise StateConflictError(f"Refusing to remove an unowned non-symlink: {path}")
    path.unlink()
    return True


def _portable_data_root(config: Config, install_root: Path) -> Path:
    expected = install_root / "data"
    managed = (
        config.live_bundle,
        config.snapshot_dir,
        config.recovery_dir,
        config.state_dir,
    )
    if not all(
        path.resolve(strict=False) == expected.resolve(strict=False)
        or expected.resolve(strict=False) in path.resolve(strict=False).parents
        for path in managed
    ):
        raise StateConflictError(
            "Data purge is unavailable because configured VM data is not wholly "
            "contained in the portable data root."
        )
    return expected


def uninstall(config: Config, arguments: list[str], *, vm_running: bool) -> str:
    purge = "--purge-data" in arguments
    approval: str | None = None
    if "--approve-path" in arguments:
        index = arguments.index("--approve-path")
        if index + 1 >= len(arguments):
            raise UsageError("Missing value for --approve-path")
        approval = arguments[index + 1]
    allowed = {"--purge-data", "--approve-path"}
    values = {approval} if approval is not None else set()
    unknown = [
        value
        for value in arguments
        if value not in allowed and value not in values
    ]
    if unknown:
        raise UsageError(f"Unknown uninstall option: {unknown[0]}")
    if approval is not None and not purge:
        raise UsageError("--approve-path requires --purge-data")

    install_root = _install_root(config)
    manifest_path = install_root / "install-manifest.json"
    manifest = read_private_json(manifest_path)
    if manifest.get("schemaVersion") != 1:
        raise ArtifactError("Install manifest schema is unsupported.")
    manifest_root = Path(str(manifest.get("installRoot", ""))).resolve(strict=False)
    if manifest_root != install_root:
        raise StateConflictError("Install manifest belongs to a different installation root.")

    data_root: Path | None = None
    if purge:
        if vm_running:
            raise StateConflictError("Data purge requires the VM runner to be stopped.")
        data_root = _portable_data_root(config, install_root)
        if approval is None or Path(approval).expanduser().resolve() != data_root.resolve():
            raise StateConflictError(
                f"Permanent data purge requires --approve-path {data_root}"
            )

    launcher = Path(str(manifest.get("launcher", ""))).resolve(strict=False)
    if launcher != config.launcher_path.resolve(strict=False):
        raise StateConflictError("Install manifest launcher does not match configuration.")
    _unlink_owned_symlink(config.launcher_path, config.launcher_path.parent)
    _unlink_owned_symlink(install_root / "current", install_root)

    releases = install_root / "releases"
    if releases.exists() or releases.is_symlink():
        permanent_delete_tree(
            releases,
            expected_root=install_root,
            category=DeletionCategory.PROGRAM_RELEASES,
            live_bundle=config.live_bundle,
        )

    result = (
        "Uninstalled vmctl program files. Configuration and VM data were preserved.\n"
        f"Preserved data: {install_root / 'data'}\n"
    )
    if data_root is not None and data_root.exists():
        permanent_delete_tree(
            data_root,
            expected_root=install_root,
            category=DeletionCategory.DATA_PURGE,
            live_bundle=config.live_bundle,
        )
        result = f"Permanently purged vmctl program files and data: {data_root}\n"
    return result
