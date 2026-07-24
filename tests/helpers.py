from __future__ import annotations

from pathlib import Path

from vmctl.config import Config
from vmctl.store import REQUIRED_VM_ARTIFACTS


def make_config(root: Path) -> Config:
    return Config(
        project_root=root,
        live_bundle=root / "live" / "VM.bundle",
        app_bundle=root / "app" / "VMRunner.app",
        snapshot_dir=root / "snapshots",
        recovery_dir=root / "recovery",
        state_dir=root / "state",
        launcher_path=root / "bin" / "vmctl",
    )


def make_bundle(path: Path, *, suspended: bool = False, marker: str = "bundle") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for artifact in REQUIRED_VM_ARTIFACTS:
        (path / artifact).write_bytes(f"{marker}:{artifact}".encode())
    if suspended:
        (path / "SaveFile.vzvmsave").write_bytes(f"{marker}:save".encode())
    return path


class FakeLifecycle:
    def __init__(self, *, running: bool = False) -> None:
        self.running = running
        self.started = False
        self.stopped = False
        self.shut_down = False

    def is_running(self) -> bool:
        return self.running

    def start(self):
        self.running = True
        self.started = True
        return {"state": "running", "pid": 99}

    def stop(self) -> None:
        self.running = False
        self.stopped = True

    def shutdown(self) -> None:
        self.running = False
        self.shut_down = True

    def status(self):
        return {
            "running": self.running,
            "pid": 99 if self.running else None,
            "runtimeState": "running" if self.running else "stopped",
            "savedState": False,
            "staleRuntime": False,
        }
