#!/usr/bin/env python3
"""Fail when public vmctl source or archives contain private/local artifacts."""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


MAX_SOURCE_BYTES = 1_048_576
PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROHIBITED_BASENAMES = {
    ".env",
    "AuxiliaryStorage",
    "Disk.img",
    "HardwareModel",
    "MachineIdentifier",
    "NetworkMACAddress",
    "SaveFile.vzvmsave",
}
PROHIBITED_SUFFIXES = {
    ".app",
    ".cer",
    ".crt",
    ".dSYM",
    ".img",
    ".ipsw",
    ".key",
    ".keychain",
    ".keychain-db",
    ".mobileprovision",
    ".p12",
    ".p8",
    ".pem",
    ".pfx",
    ".provisionprofile",
    ".vzvmsave",
}
PROHIBITED_PATH_PARTS = {
    "__pycache__",
    ".build",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".swiftpm",
    "DerivedData",
    "VM.bundle",
}
NON_GIT_GENERATED_DIRECTORIES = {
    "__pycache__",
    ".build",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".swiftpm",
    ".venv",
    "DerivedData",
    "venv",
}


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[bytes]


MACOS_HOME_PREFIX = b"/" + b"Users/"
PRIVATE_URL_PREFIXES = (
    b"git" + b"@",
    b"ssh" + b"://",
    b"file" + b"://",
)
PRIVATE_URL_HOSTS = (
    b"localhost",
    b"127.0.0.1",
)


CONTENT_RULES = (
    Rule(
        "absolute macOS home path",
        re.compile(re.escape(MACOS_HOME_PREFIX) + rb"[^/\s\"']+"),
    ),
    Rule("absolute Windows home path", re.compile(rb"[A-Za-z]:\\Users\\[^\\\s\"']+", re.I)),
    Rule(
        "personal email address",
        re.compile(rb"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    ),
    Rule(
        "personal signing identity",
        re.compile(
            rb"(?:Apple Development|Developer ID Application|Mac Developer):\s*[^\r\n\"<]+",
            re.I,
        ),
    ),
    Rule(
        "Apple team or provisioning identifier",
        re.compile(
            rb"(?:TeamIdentifier|DEVELOPMENT_TEAM|teamIdentifier|application-identifier)"
            rb"\s*[:=<>\" ]+\s*[A-Z0-9]{10}\b",
            re.I,
        ),
    ),
    Rule("personal vmctl bundle namespace", re.compile(rb"\bcom\.[a-z0-9_-]+\.vmctl\b", re.I)),
    Rule(
        "dated local baseline name",
        re.compile(rb"\bbaseline-\d{4}-\d{2}-\d{2}\b", re.I),
    ),
    Rule(
        "private key",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    Rule(
        "common provider token",
        re.compile(
            rb"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
            rb"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|"
            rb"xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{20,})"
        ),
    ),
    Rule(
        "credential assignment",
        re.compile(
            rb"\b(?:password|client_secret|api[_-]?key|auth[_-]?token)\s*[:=]\s*"
            rb"[\"']?[^\s\"']{8,}",
            re.I,
        ),
    ),
    Rule(
        "private or local URL",
        re.compile(
            rb"(?:"
            + b"|".join(re.escape(value) for value in PRIVATE_URL_PREFIXES)
            + rb"|https?://(?:"
            + b"|".join(re.escape(value) for value in PRIVATE_URL_HOSTS)
            + rb"|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|"
            rb"172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+))",
            re.I,
        ),
    ),
    Rule(
        "fixed Apple sample MAC address",
        re.compile(rb"\bd6:a7:58:8e:78:d4\b", re.I),
    ),
)


def display(path: str) -> str:
    return path.replace(str(Path.home()), "$HOME")


def path_problem(path: PurePosixPath) -> str | None:
    if path.is_absolute() or ".." in path.parts:
        return "absolute or escaping archive path"
    if any(part in PROHIBITED_PATH_PARTS for part in path.parts):
        return "prohibited generated or VM path"
    if path.name in PROHIBITED_BASENAMES or path.name.startswith(".env."):
        return "prohibited VM, local-config, or credential artifact"
    if any(path.name.endswith(suffix) for suffix in PROHIBITED_SUFFIXES):
        return "prohibited VM, build, or credential artifact"
    return None


def content_problems(data: bytes) -> list[str]:
    return [rule.name for rule in CONTENT_RULES if rule.pattern.search(data)]


def candidate_files(root: Path) -> list[Path]:
    git_directory = root / ".git"
    if not git_directory.exists() and not git_directory.is_symlink():
        return source_tree_files(root)

    result = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
    return [
        root / os.fsdecode(item)
        for item in result.stdout.split(b"\0")
        if item
    ]


def source_tree_files(root: Path) -> list[Path]:
    """Enumerate an extracted source archive after local test build products exist."""
    files: list[Path] = []
    directories = [root]
    while directories:
        directory = directories.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_symlink():
                    files.append(path)
                elif entry.is_dir(follow_symlinks=False):
                    if entry.name not in NON_GIT_GENERATED_DIRECTORIES:
                        directories.append(path)
                else:
                    files.append(path)
    return sorted(files)


def scan_file(root: Path, path: Path) -> list[str]:
    findings: list[str] = []
    relative = path.relative_to(root)
    problem = path_problem(PurePosixPath(relative.as_posix()))
    if problem:
        findings.append(problem)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        target = (path.parent / os.readlink(path)).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError:
            findings.append("symlink escapes repository")
        return findings
    if not stat.S_ISREG(metadata.st_mode):
        findings.append("not a regular source file")
        return findings
    if metadata.st_size > MAX_SOURCE_BYTES:
        findings.append(
            f"source file is {metadata.st_size} bytes; limit is {MAX_SOURCE_BYTES}"
        )
        return findings
    data = path.read_bytes()
    if b"\0" in data:
        findings.append("unexpected binary source file")
    findings.extend(content_problems(data))
    return findings


def archive_members(path: Path) -> Iterable[tuple[str, int, bytes]]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                yield member.filename, member.file_size, archive.read(member)
        return
    try:
        with tarfile.open(path, "r:*") as archive:
            for member in archive.getmembers():
                if member.issym() or member.islnk():
                    yield member.name, 0, f"SYMLINK->{member.linkname}".encode()
                elif member.isfile():
                    handle = archive.extractfile(member)
                    yield member.name, member.size, handle.read() if handle else b""
    except tarfile.TarError as error:
        raise RuntimeError(f"Unsupported archive: {path}: {error}") from error


def scan_archive(path: Path) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for name, size, data in archive_members(path):
        member = PurePosixPath(name)
        problem = path_problem(member)
        if problem:
            findings.append((name, problem))
        if size > MAX_SOURCE_BYTES:
            findings.append((name, f"archive member exceeds {MAX_SOURCE_BYTES} bytes"))
            continue
        for issue in content_problems(data):
            findings.append((name, issue))
    return findings


def scan_git_authors(root: Path) -> list[str]:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(root), "log", "--all", "--format=%an <%ae>"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return []
    identities = sorted(set(result.stdout.splitlines()))
    if not identities:
        configured_name = subprocess.run(
            ["/usr/bin/git", "-C", str(root), "config", "--get", "user.name"],
            check=False,
            text=True,
            capture_output=True,
        ).stdout.strip()
        configured_email = subprocess.run(
            ["/usr/bin/git", "-C", str(root), "config", "--get", "user.email"],
            check=False,
            text=True,
            capture_output=True,
        ).stdout.strip()
        if configured_name or configured_email:
            identities = [f"{configured_name} <{configured_email}>"]
    findings: list[str] = []
    privacy_domain = "@" + "users.noreply.github.com>"
    for identity in identities:
        if identity and not identity.endswith(privacy_domain):
            findings.append("non-noreply public Git author identity")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--archive", type=Path, action="append", default=[])
    parser.add_argument(
        "--allow-author",
        action="store_true",
        help="Skip the privacy-safe Git author check for local development only.",
    )
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    findings: list[tuple[str, str]] = []
    for path in candidate_files(root):
        for issue in scan_file(root, path):
            findings.append((str(path.relative_to(root)), issue))
    for archive in arguments.archive:
        for member, issue in scan_archive(archive):
            findings.append((f"{archive.name}:{member}", issue))
    if not arguments.allow_author:
        for issue in scan_git_authors(root):
            findings.append(("Git history", issue))

    if findings:
        for path, issue in sorted(set(findings)):
            print(f"FAIL {display(path)}: {issue}", file=sys.stderr)
        print(f"Release hygiene failed with {len(set(findings))} finding(s).", file=sys.stderr)
        return 1
    print("Release hygiene passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
