#!/usr/bin/env python3
"""Create a deterministic, source-only release archive from public candidates."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def candidates() -> list[Path]:
    result = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        capture_output=True,
        check=True,
    )
    return sorted(
        ROOT / os.fsdecode(item)
        for item in result.stdout.split(b"\0")
        if item and not os.fsdecode(item).startswith("dist/")
    )


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    output_directory = ROOT / "dist"
    output_directory.mkdir(exist_ok=True)
    archive = output_directory / f"vmctl-{version}-source.tar.gz"
    prefix = f"vmctl-{version}"
    with archive.open("wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            mtime=0,
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as package:
                for path in candidates():
                    relative = path.relative_to(ROOT)
                    if path.is_symlink() or not path.is_file():
                        raise ValueError(f"Release source must be a regular file: {relative}")
                    content = path.read_bytes()
                    info = tarfile.TarInfo(f"{prefix}/{relative.as_posix()}")
                    info.size = len(content)
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
                    package.addfile(info, io.BytesIO(content))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(archive)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
