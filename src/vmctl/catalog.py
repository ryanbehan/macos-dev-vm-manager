"""Snapshot catalog, lineage, base, and live-origin metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .errors import ArtifactError
from .store import (
    atomic_write_json,
    bundle_state,
    read_json,
    timestamp,
    validate_bundle,
    validate_snapshot_name,
)


def _display_text(value: object, *, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ArtifactError(f"Snapshot metadata has invalid {field}")
    if not value.isprintable() or any(ord(character) < 32 for character in value):
        raise ArtifactError(f"Snapshot metadata has unsafe {field}")
    return value


@dataclass(frozen=True)
class Snapshot:
    name: str
    path: Path
    created_at: str
    parent: str | None
    captured_state: str

    @classmethod
    def from_directory(cls, directory: Path) -> "Snapshot":
        if directory.is_symlink() or not directory.is_dir():
            raise ArtifactError(f"Snapshot path must be a regular directory: {directory}")
        metadata = read_json(directory / "metadata.json")
        if metadata.get("schemaVersion") != 1:
            raise ArtifactError(f"Snapshot metadata has unsupported schema: {directory}")
        name = _display_text(metadata.get("name"), field="name", maximum=80)
        validate_snapshot_name(name)
        if name != directory.name:
            raise ArtifactError(
                f"Snapshot metadata name does not match its directory: {directory}"
            )
        parent_value = metadata.get("parent")
        parent: str | None = None
        if parent_value is not None:
            parent = _display_text(parent_value, field="parent", maximum=80)
            validate_snapshot_name(parent)
            if parent == name:
                raise ArtifactError(f"Snapshot cannot name itself as parent: {name}")
        captured_state = _display_text(
            metadata.get("capturedState"), field="captured state", maximum=16
        )
        if captured_state not in {"shutdown", "suspended"}:
            raise ArtifactError(f"Snapshot metadata has invalid captured state: {directory}")
        return cls(
            name=name,
            path=directory,
            created_at=_display_text(
                metadata.get("createdAt"), field="creation timestamp", maximum=64
            ),
            parent=parent,
            captured_state=captured_state,
        )


class Catalog:
    def __init__(self, config: Config) -> None:
        self.config = config

    def snapshot_directory(self, name: str) -> Path:
        return self.config.snapshot_dir / name

    def snapshot_bundle(self, name: str) -> Path:
        return self.snapshot_directory(name) / "VM.bundle"

    def write_snapshot_metadata(
        self,
        directory: Path,
        *,
        name: str,
        parent: str | None,
        captured_state: str,
        created_at: str | None = None,
    ) -> None:
        atomic_write_json(
            directory / "metadata.json",
            {
                "schemaVersion": 1,
                "name": name,
                "createdAt": created_at or timestamp(),
                "parent": parent,
                "capturedState": captured_state,
                "bundleRelativePath": "VM.bundle",
            },
        )

    def get(self, name: str) -> Snapshot:
        directory = self.snapshot_directory(name)
        snapshot = Snapshot.from_directory(directory)
        validate_bundle(directory / "VM.bundle")
        return snapshot

    def active_snapshots(self) -> list[Snapshot]:
        if not self.config.snapshot_dir.exists():
            return []
        snapshots: list[Snapshot] = []
        for directory in sorted(self.config.snapshot_dir.iterdir()):
            if directory.is_symlink():
                raise ArtifactError(f"Snapshot catalog contains a symlink: {directory}")
            if directory.is_dir() and not directory.name.startswith("."):
                snapshots.append(Snapshot.from_directory(directory))
        return snapshots

    def get_base(self) -> str:
        value = read_json(self.config.base_file).get("snapshot")
        if not isinstance(value, str) or not value:
            raise ArtifactError(f"Base metadata is invalid: {self.config.base_file}")
        return value

    def set_base(self, name: str) -> None:
        self.get(name)
        atomic_write_json(
            self.config.base_file,
            {"schemaVersion": 1, "snapshot": name, "updatedAt": timestamp()},
        )

    def live_origin(self) -> dict[str, Any]:
        if not self.config.live_file.exists():
            return {"sourceSnapshot": None, "detached": True}
        return read_json(self.config.live_file)

    def set_live_origin(self, source: str | None, *, detached: bool = False) -> None:
        atomic_write_json(
            self.config.live_file,
            {
                "schemaVersion": 1,
                "sourceSnapshot": source,
                "loadedAt": timestamp(),
                "detached": detached,
            },
        )

    def initialize_baseline(self, name: str) -> None:
        directory = self.snapshot_directory(name)
        bundle = directory / "VM.bundle"
        validate_bundle(bundle)
        metadata = directory / "metadata.json"
        if not metadata.exists():
            self.write_snapshot_metadata(
                directory,
                name=name,
                parent=None,
                captured_state=bundle_state(bundle),
            )
        else:
            self.get(name)
        if not self.config.base_file.exists():
            self.set_base(name)
        if not self.config.live_file.exists():
            self.set_live_origin(name)

    def tree_lines(self) -> list[str]:
        active = self.active_snapshots()
        nodes = {snapshot.name: snapshot for snapshot in active}
        deleted_names = {
            snapshot.parent
            for snapshot in active
            if snapshot.parent is not None and snapshot.parent not in nodes
        }
        children: dict[str | None, list[str]] = {}
        for snapshot in active:
            children.setdefault(snapshot.parent, []).append(snapshot.name)
        for names in children.values():
            names.sort()
        roots = sorted(
            [snapshot.name for snapshot in active if snapshot.parent is None]
            + [name for name in deleted_names if name is not None]
        )
        lines: list[str] = []

        def visit(name: str, prefix: str, is_last: bool, is_root: bool = False) -> None:
            marker = "" if is_root else ("└── " if is_last else "├── ")
            deleted_marker = " [deleted]" if name in deleted_names else ""
            lines.append(f"{prefix}{marker}{name}{deleted_marker}")
            child_names = children.get(name, [])
            child_prefix = prefix + ("    " if is_last and not is_root else "│   " if not is_root else "")
            for index, child in enumerate(child_names):
                visit(child, child_prefix, index == len(child_names) - 1)

        for index, root in enumerate(roots):
            visit(root, "", index == len(roots) - 1, is_root=True)
        return lines
