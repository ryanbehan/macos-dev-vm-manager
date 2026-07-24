from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from helpers import make_bundle, make_config  # noqa: E402
from vmctl.catalog import Catalog  # noqa: E402
from vmctl.errors import ArtifactError  # noqa: E402


class CatalogTests(unittest.TestCase):
    def test_baseline_initialization_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            make_bundle(config.snapshot_dir / "baseline" / "VM.bundle", suspended=True)
            catalog = Catalog(config)
            catalog.initialize_baseline("baseline")
            first_metadata = (config.snapshot_dir / "baseline" / "metadata.json").read_text()
            catalog.initialize_baseline("baseline")
            self.assertEqual(catalog.get_base(), "baseline")
            self.assertEqual(catalog.live_origin()["sourceSnapshot"], "baseline")
            self.assertEqual(
                (config.snapshot_dir / "baseline" / "metadata.json").read_text(),
                first_metadata,
            )

    def test_incomplete_baseline_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            incomplete = config.snapshot_dir / "baseline" / "VM.bundle"
            incomplete.mkdir(parents=True)
            with self.assertRaises(Exception):
                Catalog(config).initialize_baseline("baseline")

    def test_tree_tracks_logical_parent_without_bundle_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            catalog = Catalog(config)
            for name, parent in (("base", None), ("child-a", "base"), ("child-b", "base")):
                directory = config.snapshot_dir / name
                make_bundle(directory / "VM.bundle")
                catalog.write_snapshot_metadata(
                    directory, name=name, parent=parent, captured_state="shutdown"
                )
            lines = catalog.tree_lines()
            self.assertEqual(lines[0], "base")
            self.assertTrue(any("child-a" in line for line in lines))
            self.assertTrue(any("child-b" in line for line in lines))

    def test_tree_synthesizes_deleted_parent_from_surviving_children(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            catalog = Catalog(config)
            child = config.snapshot_dir / "child"
            make_bundle(child / "VM.bundle")
            catalog.write_snapshot_metadata(
                child,
                name="child",
                parent="deleted-parent",
                captured_state="shutdown",
            )

            lines = catalog.tree_lines()

            self.assertEqual(lines[0], "deleted-parent [deleted]")
            self.assertTrue(any("child" in line for line in lines[1:]))

    def test_rejects_mismatched_or_terminal_unsafe_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            directory = config.snapshot_dir / "safe-name"
            make_bundle(directory / "VM.bundle")
            metadata = {
                "schemaVersion": 1,
                "name": "different-name",
                "createdAt": "2026-01-01T00:00:00Z",
                "parent": None,
                "capturedState": "shutdown",
                "bundleRelativePath": "VM.bundle",
            }
            (directory / "metadata.json").write_text(json.dumps(metadata))
            with self.assertRaises(ArtifactError):
                Catalog(config).get("safe-name")
            metadata["name"] = "safe-name"
            metadata["createdAt"] = "unsafe\x1b[31m"
            (directory / "metadata.json").write_text(json.dumps(metadata))
            with self.assertRaises(ArtifactError):
                Catalog(config).get("safe-name")

    def test_catalog_enumeration_rejects_symlinked_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            outside = Path(temporary) / "outside"
            outside.mkdir()
            config.snapshot_dir.mkdir()
            (config.snapshot_dir / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ArtifactError):
                Catalog(config).active_snapshots()


if __name__ == "__main__":
    unittest.main()
