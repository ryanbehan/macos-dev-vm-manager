"""Runner launch, process verification, and lifecycle control."""

from __future__ import annotations

import os
import plistlib
import signal
import stat
import subprocess
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .config import Config
from .errors import ArtifactError, LifecycleError, StateConflictError
from .store import read_json, validate_bundle


def prepare_local_runner(
    app_bundle: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Fail closed when the installed runner's trust state is unexpected."""

    quarantine = run(
        ["/usr/bin/xattr", "-p", "com.apple.quarantine", str(app_bundle)],
        text=True,
        capture_output=True,
        check=False,
    )
    if quarantine.returncode == 0:
        raise LifecycleError(
            "The VM runner is quarantined and vmctl will not alter that trust metadata.",
            hint="Rebuild or reinstall vmctl from the reviewed source checkout.",
        )

    verification = run(
        ["/usr/bin/codesign", "--verify", "--strict", "--deep", str(app_bundle)],
        text=True,
        capture_output=True,
        check=False,
    )
    if verification.returncode != 0:
        detail = verification.stderr.strip() or "codesign verification failed"
        raise LifecycleError(
            f"The staged VM runner signature is invalid: {detail}",
            hint="Run script/build_runner.sh, then vmctl doctor.",
        )

    entitlement_result = run(
        ["/usr/bin/codesign", "-d", "--entitlements", ":-", str(app_bundle)],
        text=True,
        capture_output=True,
        check=False,
    )
    entitlement_output = entitlement_result.stdout + entitlement_result.stderr
    start = entitlement_output.find("<?xml")
    end = entitlement_output.find("</plist>", start)
    if start < 0 or end < 0:
        raise LifecycleError(
            "The VM runner entitlements are missing or unreadable.",
            hint="Run script/build_runner.sh, then vmctl doctor.",
        )
    try:
        entitlements = plistlib.loads(
            entitlement_output[start : end + len("</plist>")].encode("utf-8")
        )
    except (plistlib.InvalidFileException, ValueError) as error:
        raise LifecycleError(
            "The VM runner entitlements are invalid.",
            hint="Run script/build_runner.sh, then vmctl doctor.",
        ) from error
    allowed = {
        "com.apple.security.virtualization",
    }
    if (
        entitlements.get("com.apple.security.virtualization") is not True
        or entitlements.get("com.apple.security.get-task-allow") is True
        or not set(entitlements).issubset(allowed)
    ):
        raise LifecycleError(
            "The VM runner contains missing or unapproved entitlements.",
            hint="Run script/build_runner.sh, then vmctl doctor.",
        )


class LifecycleManager:
    def __init__(
        self,
        config: Config,
        *,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        kill: Callable[[int, int], None] = os.kill,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        prepare_runner: Callable[[Path], None] | None = None,
    ) -> None:
        self.config = config
        self._run = run
        self._kill = kill
        self._sleep = sleep
        self._monotonic = monotonic
        self._prepare_runner = prepare_runner or (
            lambda app_bundle: prepare_local_runner(app_bundle, run=self._run)
        )

    def runtime(self) -> dict[str, Any] | None:
        if not self.config.runtime_file.exists():
            return None
        try:
            metadata = self.config.runtime_file.lstat()
        except FileNotFoundError:
            return None
        if (
            stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            return {"state": "invalid", "pid": None}
        try:
            return read_json(self.config.runtime_file)
        except ArtifactError:
            return {"state": "invalid", "pid": None}

    def _pid_alive(self, pid: int) -> bool:
        try:
            self._kill(pid, 0)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        return True

    def _process_matches_runner(self, pid: int) -> bool:
        result = self._run(
            ["/bin/ps", "-p", str(pid), "-o", "uid=", "-o", "comm="],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        fields = result.stdout.strip().split(maxsplit=1)
        if len(fields) != 2:
            return False
        try:
            uid = int(fields[0])
        except ValueError:
            return False
        executable = Path(fields[1]).resolve(strict=False)
        expected = self.config.runner_executable.resolve(strict=False)
        return uid == os.geteuid() and executable == expected

    def running_pid(self) -> int | None:
        runtime = self.runtime()
        if runtime is None:
            return None
        pid = runtime.get("pid")
        if not isinstance(pid, int) or pid <= 0 or not self._pid_alive(pid):
            return None
        if not self._process_matches_runner(pid):
            return None
        return pid

    def _signal_verified(self, pid: int, signal_number: int) -> None:
        if not self._pid_alive(pid) or not self._process_matches_runner(pid):
            raise StateConflictError(
                "The recorded VM runner process no longer matches the installed runner."
            )
        self._kill(pid, signal_number)

    def is_running(self) -> bool:
        return self.running_pid() is not None

    def start(self, *, timeout: float = 300.0) -> dict[str, Any]:
        validate_bundle(self.config.live_bundle)
        if not self.config.app_bundle.is_dir() or not self.config.runner_executable.is_file():
            raise ArtifactError(
                f"Staged runner is missing: {self.config.app_bundle}",
                hint="Run script/build_runner.sh, then vmctl doctor.",
            )
        if self.is_running():
            raise StateConflictError("The VM is already running.")
        self._prepare_runner(self.config.app_bundle)
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        if self.config.runtime_file.exists():
            self.config.runtime_file.unlink()
        if self.config.control_response_file.exists():
            self.config.control_response_file.unlink()
        result = self._run(
            [
                "/usr/bin/open",
                "-n",
                "--arch",
                "arm64",
                str(self.config.app_bundle),
                "--args",
                "--vm-bundle",
                str(self.config.live_bundle),
                "--control-dir",
                str(self.config.state_dir),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise LifecycleError(
                f"Failed to launch the VM runner: {result.stderr.strip()}"
            )
        deadline = self._monotonic() + timeout
        while self._monotonic() < deadline:
            runtime = self.runtime()
            if runtime and runtime.get("state") == "running":
                return runtime
            if runtime and runtime.get("state") == "error":
                raise LifecycleError(str(runtime.get("message", "Runner failed.")))
            self._sleep(0.2)
        raise LifecycleError(
            "Timed out waiting for the VM runner to finish starting or restoring.",
            hint="Run vmctl status and vmctl doctor.",
        )

    def _wait_for_exit(self, pid: int, timeout: float) -> None:
        deadline = self._monotonic() + timeout
        while self._monotonic() < deadline:
            if not self._pid_alive(pid):
                return
            self._sleep(0.2)
        raise LifecycleError(
            f"Timed out waiting for VM runner process {pid} to exit; it was not force-killed."
        )

    def stop(self, *, timeout: float = 180.0) -> None:
        pid = self.running_pid()
        if pid is None:
            raise StateConflictError("The VM is not running.")
        self._signal_verified(pid, signal.SIGUSR2)
        self._wait_for_exit(pid, timeout)
        save_file = self.config.live_bundle / "SaveFile.vzvmsave"
        if not save_file.is_file() or save_file.stat().st_size == 0:
            raise LifecycleError(
                "The runner exited without producing a resumable saved state."
            )

    def shutdown(self, *, timeout: float = 120.0) -> None:
        pid = self.running_pid()
        if pid is None:
            raise StateConflictError("The VM is not running.")
        if self.config.control_response_file.exists():
            self.config.control_response_file.unlink()
        self._signal_verified(pid, signal.SIGUSR1)
        deadline = self._monotonic() + min(timeout, 10.0)
        response: dict[str, Any] | None = None
        while self._monotonic() < deadline:
            if self.config.control_response_file.exists():
                response = read_json(self.config.control_response_file)
                break
            self._sleep(0.2)
        if response is None:
            raise LifecycleError("The runner did not acknowledge the shutdown request.")
        if response.get("status") != "accepted":
            raise LifecycleError(
                str(response.get("message", "Guest shutdown request was rejected."))
            )
        remaining = max(1.0, timeout - 10.0)
        try:
            self._wait_for_exit(pid, remaining)
        except LifecycleError as error:
            raise LifecycleError(
                "The guest accepted shutdown but has not exited yet.",
                hint="Check the VM window for macOS's shutdown confirmation, then run vmctl status.",
            ) from error

    def status(self) -> dict[str, Any]:
        runtime = self.runtime()
        pid = self.running_pid()
        save_file = self.config.live_bundle / "SaveFile.vzvmsave"
        runtime_state = runtime.get("state") if runtime else None
        active_states = {
            "starting",
            "restoring",
            "running",
            "suspending",
            "shutdown-requested",
        }
        return {
            "running": pid is not None,
            "pid": pid,
            "runtimeState": runtime_state,
            "savedState": save_file.is_file() and save_file.stat().st_size > 0,
            "staleRuntime": runtime_state in active_states and pid is None,
        }
