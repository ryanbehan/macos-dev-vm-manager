"""Terminal-safe redaction for diagnostics intended for public sharing."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .config import Config


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def redact_text(value: str, config: Config) -> str:
    text = _CONTROL.sub("?", value)
    home = str(Path.home())
    configured_home = str(
        config.config_file.parents[3]
        if config.config_file is not None and len(config.config_file.parents) >= 4
        else Path.home()
    )
    replacements = {
        home: "$HOME",
        configured_home: "$HOME",
        os.environ.get("USER", ""): "<user>",
        str(config.live_bundle): "<live-vm>",
        str(config.snapshot_dir): "<snapshots>",
        str(config.recovery_dir): "<recovery>",
        str(config.state_dir): "<state>",
        str(config.app_bundle): "<runner-app>",
        str(config.launcher_path): "<launcher>",
    }
    for original in sorted(
        (key for key in replacements if key), key=len, reverse=True
    ):
        text = text.replace(original, replacements[original])
    text = re.sub(r"<snapshots>/[^\s:;,]+", "<snapshots>/<snapshot>", text)
    return text


def redact_check(check, config: Config):
    from .doctor import Check

    detail = redact_text(check.detail, config)
    if check.name == "base snapshot" and check.level == "PASS":
        detail = "<snapshot>"
    if check.name == "runner signing":
        detail = detail.split(":", 1)[0]
    return Check(check.level, check.name, detail)
