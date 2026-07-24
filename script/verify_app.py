#!/usr/bin/env python3
"""Strictly verify the staged VMRunner app and nested installer."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


RUNNER_ENTITLEMENTS = {
    "com.apple.security.virtualization",
}
INSTALLER_ENTITLEMENTS = {"com.apple.security.virtualization"}
CODESIGN = os.environ.get("VMCTL_CODESIGN_BIN", "/usr/bin/codesign")


def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        text=True,
        capture_output=True,
        check=False,
    )


def entitlements(path: Path) -> dict[str, object]:
    result = run([CODESIGN, "-d", "--entitlements", ":-", str(path)])
    output = result.stdout + result.stderr
    start = output.find("<?xml")
    end = output.find("</plist>", start)
    if result.returncode != 0 or start < 0 or end < 0:
        raise ValueError(f"Entitlements are unreadable: {path}")
    value = plistlib.loads(output[start : end + len("</plist>")].encode())
    if not isinstance(value, dict):
        raise ValueError(f"Entitlements are not a dictionary: {path}")
    return value


def verify_entitlements(
    path: Path,
    *,
    allowed: set[str],
    require_audio: bool,
) -> None:
    value = entitlements(path)
    if value.get("com.apple.security.virtualization") is not True:
        raise ValueError(f"Virtualization entitlement is missing: {path}")
    if value.get("com.apple.security.get-task-allow") is True:
        raise ValueError(f"get-task-allow is prohibited: {path}")
    if not set(value).issubset(allowed):
        unexpected = sorted(set(value) - allowed)
        raise ValueError(f"Unexpected entitlements in {path}: {unexpected}")
    if require_audio and value.get("com.apple.security.device.audio-input") is not True:
        raise ValueError(f"Audio-input entitlement is missing: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    arguments = parser.parse_args(argv)
    app = arguments.app.resolve()
    runner = app / "Contents" / "MacOS" / "VMRunner"
    installer = app / "Contents" / "Helpers" / "VMInstaller"
    info = app / "Contents" / "Info.plist"
    for path in (runner, installer, info):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Required app file is missing or symlinked: {path}")

    plist = plistlib.loads(info.read_bytes())
    if plist.get("CFBundleIdentifier") != "dev.vmctl.runner":
        raise ValueError("Unexpected runner bundle identifier")
    if plist.get("CFBundleExecutable") != "VMRunner":
        raise ValueError("Unexpected runner executable")

    for path in (installer, app):
        result = run([CODESIGN, "--verify", "--strict", "--verbose=2", str(path)])
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or f"Signature validation failed: {path}")

    verify_entitlements(
        installer,
        allowed=INSTALLER_ENTITLEMENTS,
        require_audio=False,
    )
    verify_entitlements(
        app,
        allowed=RUNNER_ENTITLEMENTS,
        require_audio=False,
    )
    print(f"Verified app: {app}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        print(f"verify_app: {error}", file=sys.stderr)
        raise SystemExit(1)
