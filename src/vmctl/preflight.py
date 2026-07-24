"""Non-mutating dependency checks for source builds and installations."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


Run = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class PreflightCheck:
    level: str
    name: str
    detail: str
    next_action: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", text)
    if not match:
        return ()
    return tuple(int(value or 0) for value in match.groups())


def _command(
    arguments: list[str],
    *,
    run: Run,
) -> subprocess.CompletedProcess[str]:
    return run(arguments, text=True, capture_output=True, check=False)


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _launcher_is_managed(launcher: Path, install_root: Path, source_root: Path) -> bool:
    if not launcher.exists() and not launcher.is_symlink():
        return True
    if not launcher.is_symlink():
        return False
    resolved = launcher.resolve(strict=False)
    return (
        resolved == (source_root / "vmctl").resolve(strict=False)
        or install_root.resolve(strict=False) in resolved.parents
    )


def run_preflight(
    *,
    source_root: Path,
    install_root: Path,
    data_root: Path,
    launcher: Path,
    run: Run = subprocess.run,
) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    system = platform.system()
    checks.append(
        PreflightCheck("PASS" if system == "Darwin" else "FAIL", "platform", system)
    )
    architecture = platform.machine()
    checks.append(
        PreflightCheck(
            "PASS" if architecture in {"arm64", "arm64e"} else "FAIL",
            "architecture",
            architecture,
            "Use an Apple silicon Mac.",
        )
    )
    mac_version = parse_version(platform.mac_ver()[0])
    checks.append(
        PreflightCheck(
            "PASS" if mac_version >= (26, 0, 0) else "FAIL",
            "macOS",
            platform.mac_ver()[0] or "unknown",
            "Use macOS 26 or newer for the validated 0.1.0 source release.",
        )
    )
    python_version = sys.version_info[:3]
    checks.append(
        PreflightCheck(
            "PASS" if python_version >= (3, 10, 0) else "FAIL",
            "Python",
            ".".join(str(value) for value in python_version),
            "Install Python 3.10 or newer and rerun the installer.",
        )
    )

    selected = _command(["/usr/bin/xcode-select", "-p"], run=run)
    developer_tools = selected.returncode == 0 and bool(selected.stdout.strip())
    checks.append(
        PreflightCheck(
            "PASS" if developer_tools else "FAIL",
            "Command Line Tools",
            selected.stdout.strip() if developer_tools else "not selected",
            "Run `xcode-select --install`, finish Apple's installer, then rerun this command.",
        )
    )
    swift = _command(["/usr/bin/xcrun", "--find", "swift"], run=run)
    swift_path = swift.stdout.strip() if swift.returncode == 0 else ""
    swift_version_result = (
        _command([swift_path, "--version"], run=run)
        if swift_path
        else subprocess.CompletedProcess([], 1, "", "")
    )
    swift_version = parse_version(swift_version_result.stdout + swift_version_result.stderr)
    checks.append(
        PreflightCheck(
            "PASS" if swift_version >= (6, 0, 0) else "FAIL",
            "Swift",
            swift_version_result.stdout.strip() or swift_version_result.stderr.strip() or "not found",
            "Install newer Apple Command Line Tools or select a compatible full Xcode.",
        )
    )
    sdk = _command(["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"], run=run)
    checks.append(
        PreflightCheck(
            "PASS" if sdk.returncode == 0 and Path(sdk.stdout.strip()).is_dir() else "FAIL",
            "macOS SDK",
            sdk.stdout.strip() or "not found",
            "Install or select Apple Command Line Tools containing the macOS SDK.",
        )
    )

    for executable in (
        "/usr/bin/codesign",
        "/usr/bin/xattr",
        "/bin/cp",
        "/usr/bin/open",
        "/usr/bin/git",
    ):
        checks.append(
            PreflightCheck(
                "PASS" if Path(executable).is_file() else "FAIL",
                f"tool {Path(executable).name}",
                executable,
            )
        )

    data_probe = _existing_ancestor(data_root)
    filesystem_device = _command(["/bin/df", str(data_probe)], run=run)
    lines = filesystem_device.stdout.splitlines()
    device = lines[-1].split()[0] if filesystem_device.returncode == 0 and len(lines) >= 2 else ""
    filesystem = (
        _command(["/usr/sbin/diskutil", "info", device], run=run)
        if device
        else subprocess.CompletedProcess([], 1, "", "")
    )
    filesystem_name = "apfs" if re.search(
        r"(?:File System Personality|Type \(Bundle\)):\s*APFS\b",
        filesystem.stdout,
        re.I,
    ) else "unknown"
    checks.append(
        PreflightCheck(
            "PASS" if filesystem.returncode == 0 and filesystem_name == "apfs" else "FAIL",
            "data filesystem",
            filesystem_name or "unknown",
            "Choose an APFS data location for safe copy-on-write snapshots.",
        )
    )
    free = shutil.disk_usage(data_probe).free
    checks.append(
        PreflightCheck(
            "PASS" if free >= 5 * 1024**3 else "FAIL",
            "installation storage",
            f"{free / 1024**3:.1f} GiB free",
            "Free at least 5 GiB before installing the program.",
        )
    )
    checks.append(
        PreflightCheck(
            "PASS" if _launcher_is_managed(launcher, install_root, source_root) else "FAIL",
            "launcher",
            str(launcher).replace(str(Path.home()), "$HOME"),
            "Move the unrelated launcher or set VMCTL_LAUNCHER_PATH explicitly.",
        )
    )
    checks.append(
        PreflightCheck(
            "PASS" if (source_root / "VERSION").is_file() else "FAIL",
            "source checkout",
            str(source_root),
        )
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    arguments = parser.parse_args(argv)
    checks = run_preflight(
        source_root=arguments.source_root.resolve(),
        install_root=arguments.install_root.expanduser().resolve(),
        data_root=arguments.data_root.expanduser().resolve(),
        launcher=Path(os.path.abspath(arguments.launcher.expanduser())),
    )
    failed = False
    for check in checks:
        print(f"{check.level} {check.name}: {check.detail}")
        if check.level == "FAIL":
            failed = True
            if check.next_action:
                print(f"NEXT {check.next_action}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
