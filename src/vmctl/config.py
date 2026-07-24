"""Path configuration for vmctl."""

from __future__ import annotations

import os
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping


CONFIG_SCHEMA_VERSION = 1


def project_root_from_source() -> Path:
    return Path(__file__).resolve().parents[2]


def _configured_path(
    environment: Mapping[str, str],
    key: str,
    configured: object,
    default: Path,
) -> Path:
    value = environment.get(key)
    candidate = value if value is not None else configured
    if candidate is None:
        candidate = default
    if not isinstance(candidate, (str, os.PathLike)):
        raise ValueError(f"{key} must resolve to a filesystem path")
    text = os.fspath(candidate)
    if "\0" in text:
        raise ValueError(f"{key} contains a null byte")
    expanded = Path(text).expanduser()
    return Path(os.path.abspath(expanded))


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _read_installed_config(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Configuration must be a regular file: {path}")
    metadata = path.lstat()
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(f"Configuration must be private and owned by the current user: {path}")
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("schemaVersion") != CONFIG_SCHEMA_VERSION:
        raise ValueError(f"Unsupported or invalid configuration: {path}")
    allowed = {
        "schemaVersion",
        "liveBundle",
        "snapshotDirectory",
        "recoveryDirectory",
        "stateDirectory",
        "runnerApplication",
        "launcher",
    }
    if not set(value).issubset(allowed):
        raise ValueError(f"Configuration contains unknown fields: {path}")
    for key in allowed - {"schemaVersion"}:
        if key in value and not isinstance(value[key], str):
            raise ValueError(f"Configuration field {key} must be a path string: {path}")
    return value


@dataclass(frozen=True)
class Config:
    project_root: Path
    live_bundle: Path
    app_bundle: Path
    snapshot_dir: Path
    recovery_dir: Path
    state_dir: Path
    launcher_path: Path
    config_file: Path | None = None

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        project_root: Path | None = None,
    ) -> "Config":
        env = os.environ if environment is None else environment
        root = (project_root or project_root_from_source()).resolve()
        home = Path(env.get("HOME", str(Path.home()))).expanduser().resolve()
        support_root = home / "Library" / "Application Support" / "vmctl"
        config_file = Path(
            os.path.abspath(
                Path(
                    env.get("VMCTL_CONFIG_FILE", str(support_root / "config.json"))
                ).expanduser()
            )
        )
        configured = _read_installed_config(config_file)
        legacy_layout = (
            not configured
            and (root / "state" / "base.json").is_file()
            and (root / "snapshots").is_dir()
        )
        data_root = support_root / "data"
        default_live = home / "VM.bundle" if legacy_layout else data_root / "live" / "VM.bundle"
        default_app = (
            root / "app" / "VMRunner.app"
            if legacy_layout
            else support_root / "current" / "libexec" / "VMRunner.app"
        )
        default_snapshots = root / "snapshots" if legacy_layout else data_root / "snapshots"
        default_recovery = root / "recovery" if legacy_layout else data_root / "recovery"
        default_state = root / "state" if legacy_layout else data_root / "state"
        return cls(
            project_root=root,
            live_bundle=_configured_path(
                env, "VMCTL_LIVE_BUNDLE", configured.get("liveBundle"), default_live
            ),
            app_bundle=_configured_path(
                env, "VMCTL_APP_BUNDLE", configured.get("runnerApplication"), default_app
            ),
            snapshot_dir=_configured_path(
                env, "VMCTL_SNAPSHOT_DIR", configured.get("snapshotDirectory"), default_snapshots
            ),
            recovery_dir=_configured_path(
                env, "VMCTL_RECOVERY_DIR", configured.get("recoveryDirectory"), default_recovery
            ),
            state_dir=_configured_path(
                env, "VMCTL_STATE_DIR", configured.get("stateDirectory"), default_state
            ),
            launcher_path=_configured_path(
                env,
                "VMCTL_LAUNCHER_PATH",
                configured.get("launcher"),
                home / ".local" / "bin" / "vmctl",
            ),
            config_file=config_file,
        )

    @property
    def base_file(self) -> Path:
        return self.state_dir / "base.json"

    @property
    def live_file(self) -> Path:
        return self.state_dir / "live.json"

    @property
    def runtime_file(self) -> Path:
        return self.state_dir / "runtime.json"

    @property
    def control_response_file(self) -> Path:
        return self.state_dir / "control-response.json"

    @property
    def transaction_file(self) -> Path:
        return self.state_dir / "transaction.json"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / "vmctl.lock"

    @property
    def runner_executable(self) -> Path:
        return self.app_bundle / "Contents" / "MacOS" / "VMRunner"

    def ensure_data_directories(self) -> None:
        _private_directory(self.snapshot_dir)
        _private_directory(self.state_dir)
        _private_directory(self.recovery_dir)
        for child in ("pending", "failed"):
            _private_directory(self.recovery_dir / child)
