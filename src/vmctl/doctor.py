"""Read-only environment and artifact diagnostics."""

from __future__ import annotations

import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from collections.abc import Callable

from .catalog import Catalog
from .config import Config
from .store import validate_bundle
from .transactions import read_transaction
from . import __version__


def _entitlements(
    app_bundle,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, object] | None:
    result = run(
        ["/usr/bin/codesign", "-d", "--entitlements", ":-", str(app_bundle)],
        text=True,
        capture_output=True,
        check=False,
    )
    content = result.stdout + result.stderr
    start = content.find("<?xml")
    end = content.find("</plist>", start)
    if result.returncode != 0 or start < 0 or end < 0:
        return None
    try:
        value = plistlib.loads(
            content[start : end + len("</plist>")].encode("utf-8")
        )
    except (ValueError, plistlib.InvalidFileException):
        return None
    return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class Check:
    level: str
    name: str
    detail: str


def run_checks(
    config: Config,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[Check]:
    checks: list[Check] = []
    checks.append(Check("PASS", "vmctl version", f"{__version__} protocol=1"))
    checks.append(
        Check(
            "PASS" if sys.version_info >= (3, 10) else "FAIL",
            "python runtime",
            f"{sys.executable} {platform.python_version()}",
        )
    )
    if config.config_file is not None:
        config_ok = config.config_file.is_file() and not config.config_file.is_symlink()
        checks.append(
            Check(
                "PASS" if config_ok else "WARN",
                "configuration",
                str(config.config_file) if config_ok else "portable defaults in use",
            )
        )
    system = platform.system()
    checks.append(Check("PASS" if system == "Darwin" else "FAIL", "platform", system))
    architecture = platform.machine()
    checks.append(
        Check(
            "PASS" if architecture == "arm64" else "FAIL",
            "architecture",
            architecture,
        )
    )
    if not config.live_bundle.exists() and not config.live_bundle.is_symlink():
        checks.append(Check("WARN", "live bundle", "not initialized"))
    else:
        try:
            validate_bundle(config.live_bundle)
            checks.append(Check("PASS", "live bundle", str(config.live_bundle)))
        except Exception as error:
            checks.append(Check("FAIL", "live bundle", str(error)))

    catalog = Catalog(config)
    snapshot_directory_ok = config.snapshot_dir.is_dir() and os.access(
        config.snapshot_dir, os.R_OK | os.W_OK
    )
    checks.append(
        Check(
            "PASS" if snapshot_directory_ok else "WARN",
            "snapshot directory",
            str(config.snapshot_dir) if snapshot_directory_ok else "not initialized",
        )
    )
    try:
        base = catalog.get_base()
        catalog.get(base)
        checks.append(Check("PASS", "base snapshot", base))
    except Exception as error:
        level = "WARN" if not config.base_file.exists() else "FAIL"
        detail = "not initialized" if level == "WARN" else str(error)
        checks.append(Check(level, "base snapshot", detail))

    try:
        journal = read_transaction(config)
        checks.append(
            Check(
                "WARN" if journal is not None else "PASS",
                "transaction state",
                (
                    f"unfinished {journal.get('operation')} transaction in {journal.get('phase')} phase"
                    if journal is not None
                    else "none"
                ),
            )
        )
    except Exception as error:
        checks.append(Check("FAIL", "transaction state", str(error)))

    def entry_count(path) -> int:
        return sum(1 for _ in path.iterdir()) if path.is_dir() else 0

    pending_count = entry_count(config.recovery_dir / "pending")
    failed_count = entry_count(config.recovery_dir / "failed")
    legacy_count = sum(
        entry_count(config.recovery_dir / name) for name in ("live", "removed")
    )
    checks.append(
        Check(
            "WARN" if pending_count else "PASS",
            "pending rollback",
            f"{pending_count} entr{'y' if pending_count == 1 else 'ies'}",
        )
    )
    checks.append(
        Check(
            "WARN" if failed_count else "PASS",
            "failed recovery",
            f"{failed_count} entr{'y' if failed_count == 1 else 'ies'}",
        )
    )
    checks.append(
        Check(
            "WARN" if legacy_count else "PASS",
            "legacy recovery",
            (
                f"{legacy_count} entries require separately reviewed migration"
                if legacy_count
                else "none"
            ),
        )
    )

    if config.runner_executable.is_file():
        verify = run(
            [
                "/usr/bin/codesign",
                "--verify",
                "--strict",
                "--deep",
                str(config.app_bundle),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        checks.append(
            Check(
                "PASS" if verify.returncode == 0 else "FAIL",
                "runner signature",
                str(config.app_bundle)
                if verify.returncode == 0
                else (verify.stderr.strip() or "codesign verification failed"),
            )
        )
        entitlements = _entitlements(config.app_bundle, run)
        allowed = {
            "com.apple.security.virtualization",
        }
        entitlement_ok = (
            entitlements is not None
            and entitlements.get("com.apple.security.virtualization") is True
            and entitlements.get("com.apple.security.get-task-allow") is not True
            and set(entitlements).issubset(allowed)
        )
        checks.append(
            Check(
                "PASS" if entitlement_ok else "FAIL",
                "virtualization entitlement",
                "exact approved entitlement set"
                if entitlement_ok
                else "missing, unreadable, or unapproved entitlement",
            )
        )
        details = run(
            ["/usr/bin/codesign", "-d", "-vv", str(config.app_bundle)],
            text=True,
            capture_output=True,
            check=False,
        )
        signing_output = details.stdout + details.stderr
        signing_class = (
            "Developer ID"
            if "Developer ID Application:" in signing_output
            else "Apple Development"
            if "Apple Development:" in signing_output
            else "ad hoc/local"
        )
        checks.append(Check("PASS", "runner signing", signing_class))
        quarantine = run(
            [
                "/usr/bin/xattr",
                "-p",
                "com.apple.quarantine",
                str(config.app_bundle),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        checks.append(
            Check(
                "WARN" if quarantine.returncode == 0 else "PASS",
                "runner quarantine",
                (
                    "present; reinstall from reviewed source before launch"
                    if quarantine.returncode == 0
                    else "not present"
                ),
            )
        )
    else:
        checks.append(Check("FAIL", "runner signature", f"missing: {config.app_bundle}"))
        checks.append(Check("FAIL", "virtualization entitlement", "runner missing"))
        checks.append(Check("FAIL", "runner signing", "runner missing"))
        checks.append(Check("FAIL", "runner quarantine", "runner missing"))

    storage_probe = config.snapshot_dir
    while not storage_probe.exists() and storage_probe != storage_probe.parent:
        storage_probe = storage_probe.parent
    usage = shutil.disk_usage(storage_probe)
    free_gib = usage.free / (1024**3)
    checks.append(
        Check(
            "PASS" if free_gib >= 20 else "WARN",
            "available storage",
            f"{free_gib:.1f} GiB free",
        )
    )
    device_result = run(
        ["/bin/df", str(storage_probe)],
        text=True,
        capture_output=True,
        check=False,
    )
    device_lines = device_result.stdout.splitlines()
    device = (
        device_lines[-1].split()[0]
        if device_result.returncode == 0 and len(device_lines) >= 2
        else ""
    )
    disk_info = (
        run(
            ["/usr/sbin/diskutil", "info", device],
            text=True,
            capture_output=True,
            check=False,
        )
        if device
        else subprocess.CompletedProcess([], 1, "", "")
    )
    apfs = bool(
        re.search(
            r"(?:File System Personality|Type \(Bundle\)):\s*APFS\b",
            disk_info.stdout,
            re.I,
        )
    )
    checks.append(
        Check(
            "PASS" if apfs else "FAIL",
            "data filesystem",
            "APFS" if apfs else "not APFS or unavailable",
        )
    )
    resolved = shutil.which("vmctl")
    expected = str(config.launcher_path)
    path_ok = resolved is not None and os.path.realpath(resolved) == os.path.realpath(
        config.launcher_path
    )
    checks.append(
        Check(
            "PASS" if path_ok else "WARN",
            "shell path",
            resolved or f"not resolved; expected {expected}",
        )
    )
    return checks
