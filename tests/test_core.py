from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from helpers import make_bundle, make_config  # noqa: E402
from vmctl.config import Config  # noqa: E402
from vmctl.errors import ArtifactError, StateConflictError, TransactionError, UsageError  # noqa: E402
from vmctl.store import (  # noqa: E402
    DeletionCategory,
    FileLock,
    atomic_write_json,
    bundle_state,
    clone_bundle,
    permanent_delete_tree,
    read_json,
    validate_bundle,
    validate_snapshot_name,
)


class CoreTests(unittest.TestCase):
    def test_configuration_honors_path_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = Config.from_environment(
                {
                    "HOME": str(root),
                    "VMCTL_LIVE_BUNDLE": str(root / "custom.bundle"),
                },
                project_root=root,
            )
            self.assertEqual(
                config.live_bundle,
                Path(os.path.abspath(root / "custom.bundle")),
            )
            self.assertEqual(
                config.snapshot_dir,
                (root / "Library/Application Support/vmctl/data/snapshots").resolve(),
            )

    def test_installed_configuration_rejects_unknown_schema_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "Library/Application Support/vmctl/config.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"schemaVersion": 1, "unexpected": "value"}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                Config.from_environment({"HOME": str(root)}, project_root=root / "source")

    def test_stable_current_and_launcher_paths_are_not_dereferenced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            install = root / "Library/Application Support/vmctl"
            release = install / "releases/0.1.0"
            (release / "libexec/VMRunner.app").mkdir(parents=True)
            (release / "bin").mkdir()
            (release / "bin/vmctl").write_text("launcher", encoding="utf-8")
            (install / "current").symlink_to("releases/0.1.0")
            launcher = root / ".local/bin/vmctl"
            launcher.parent.mkdir(parents=True)
            launcher.symlink_to(install / "current/bin/vmctl")
            config = Config.from_environment(
                {"HOME": str(root)},
                project_root=root / "source",
            )
            self.assertEqual(
                config.app_bundle,
                install / "current/libexec/VMRunner.app",
            )
            self.assertEqual(config.launcher_path, launcher)

    def test_snapshot_name_validation(self) -> None:
        for valid in ("baseline-1", "dev.ready", "A_2"):
            self.assertEqual(validate_snapshot_name(valid), valid)
        for invalid in ("", "../bad", "/absolute", "-leading", "trailing-", "bad name"):
            with self.subTest(invalid=invalid), self.assertRaises(UsageError):
                validate_snapshot_name(invalid)

    def test_bundle_validation_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = make_bundle(root / "VM.bundle", suspended=True)
            validate_bundle(bundle)
            self.assertEqual(bundle_state(bundle), "suspended")
            (bundle / "Disk.img").unlink()
            with self.assertRaises(ArtifactError):
                validate_bundle(bundle)

    def test_atomic_json_replaces_complete_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state" / "value.json"
            atomic_write_json(path, {"value": 1})
            atomic_write_json(path, {"value": 2, "ok": True})
            self.assertEqual(read_json(path), {"value": 2, "ok": True})
            self.assertEqual(json.loads(path.read_text()), {"value": 2, "ok": True})

    def test_file_lock_rejects_contention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "state/vmctl.lock"
            with FileLock(lock_path):
                with self.assertRaises(StateConflictError):
                    with FileLock(lock_path):
                        self.fail("contended lock was acquired")

    def test_clone_uses_apfs_copy_flags_and_validates_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_bundle(root / "source.bundle")
            destination = root / "destination.bundle"
            calls: list[list[str]] = []

            def fake_run(arguments, **kwargs):
                calls.append(arguments)
                shutil.copytree(source, destination)
                return subprocess.CompletedProcess(arguments, 0, "", "")

            clone_bundle(source, destination, runner=fake_run)
            self.assertEqual(calls, [["/bin/cp", "-a", "-c", str(source), str(destination)]])

    def test_clone_failure_does_not_accept_incomplete_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_bundle(root / "source.bundle")
            destination = root / "destination.bundle"

            def incomplete_copy(arguments, **kwargs):
                destination.mkdir()
                (destination / "Disk.img").write_bytes(b"disk")
                return subprocess.CompletedProcess(arguments, 0, "", "")

            with self.assertRaises(ArtifactError):
                clone_bundle(source, destination, runner=incomplete_copy)
            self.assertTrue(destination.exists())

    def test_permanent_delete_removes_only_eligible_direct_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_root = root / "snapshots"
            target = make_bundle(snapshot_root / "throwaway" / "VM.bundle")
            snapshot = target.parent
            (snapshot / "metadata.json").write_text("{}\n")
            unrelated = make_bundle(snapshot_root / "keep" / "VM.bundle")

            permanent_delete_tree(
                snapshot,
                expected_root=snapshot_root,
                category=DeletionCategory.SNAPSHOT,
                live_bundle=root / "live" / "VM.bundle",
            )

            self.assertFalse(snapshot.exists())
            self.assertTrue(unrelated.exists())

    def test_permanent_delete_rejects_deletion_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_root = root / "snapshots"
            make_bundle(snapshot_root / "keep" / "VM.bundle")

            with self.assertRaises(TransactionError):
                permanent_delete_tree(
                    snapshot_root,
                    expected_root=snapshot_root,
                    category=DeletionCategory.SNAPSHOT,
                    live_bundle=root / "live" / "VM.bundle",
                )

            self.assertTrue(snapshot_root.exists())

    def test_permanent_delete_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_root = root / "snapshots"
            snapshot_root.mkdir()
            outside = make_bundle(root / "outside" / "VM.bundle").parent

            with self.assertRaises(TransactionError):
                permanent_delete_tree(
                    snapshot_root / ".." / "outside",
                    expected_root=snapshot_root,
                    category=DeletionCategory.SNAPSHOT,
                    live_bundle=root / "live" / "VM.bundle",
                )

            self.assertTrue(outside.exists())

    def test_permanent_delete_rejects_absolute_path_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_root = root / "snapshots"
            snapshot_root.mkdir()
            outside = make_bundle(root / "outside" / "VM.bundle").parent

            with self.assertRaises(TransactionError):
                permanent_delete_tree(
                    outside,
                    expected_root=snapshot_root,
                    category=DeletionCategory.SNAPSHOT,
                    live_bundle=root / "live" / "VM.bundle",
                )

            self.assertTrue(outside.exists())

    def test_permanent_delete_rejects_nested_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_root = root / "snapshots"
            nested = make_bundle(snapshot_root / "parent" / "nested" / "VM.bundle").parent

            with self.assertRaises(TransactionError):
                permanent_delete_tree(
                    nested,
                    expected_root=snapshot_root,
                    category=DeletionCategory.SNAPSHOT,
                    live_bundle=root / "live" / "VM.bundle",
                )

            self.assertTrue(nested.exists())

    def test_permanent_delete_rejects_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_root = root / "snapshots"
            snapshot_root.mkdir()
            outside = make_bundle(root / "outside" / "VM.bundle").parent
            link = snapshot_root / "linked"
            link.symlink_to(outside, target_is_directory=True)

            with self.assertRaises(TransactionError):
                permanent_delete_tree(
                    link,
                    expected_root=snapshot_root,
                    category=DeletionCategory.SNAPSHOT,
                    live_bundle=root / "live" / "VM.bundle",
                )

            self.assertTrue(link.is_symlink())
            self.assertTrue(outside.exists())

    def test_permanent_delete_rejects_live_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            live_bundle = make_bundle(root / "live-root" / "VM.bundle")

            with self.assertRaises(StateConflictError):
                permanent_delete_tree(
                    live_bundle,
                    expected_root=live_bundle.parent,
                    category=DeletionCategory.TRANSACTION_TEMPORARY,
                    live_bundle=live_bundle,
                )

            self.assertTrue(live_bundle.exists())

    def test_permanent_delete_rejects_protected_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_root = root / "snapshots"
            protected = make_bundle(snapshot_root / "base" / "VM.bundle").parent

            with self.assertRaises(StateConflictError):
                permanent_delete_tree(
                    protected,
                    expected_root=snapshot_root,
                    category=DeletionCategory.SNAPSHOT,
                    live_bundle=root / "live" / "VM.bundle",
                    protected_paths=(protected,),
                )

            self.assertTrue(protected.exists())

    def test_permanent_delete_rejects_missing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_root = root / "snapshots"
            snapshot_root.mkdir()

            with self.assertRaises(ArtifactError):
                permanent_delete_tree(
                    snapshot_root / "missing",
                    expected_root=snapshot_root,
                    category=DeletionCategory.SNAPSHOT,
                    live_bundle=root / "live" / "VM.bundle",
                )

    def test_permanent_delete_requires_typed_category(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_root = root / "snapshots"
            target = make_bundle(snapshot_root / "throwaway" / "VM.bundle").parent

            with self.assertRaises(TransactionError):
                permanent_delete_tree(
                    target,
                    expected_root=snapshot_root,
                    category="snapshot",  # type: ignore[arg-type]
                    live_bundle=root / "live" / "VM.bundle",
                )

            self.assertTrue(target.exists())

    def test_data_directory_initialization_uses_bounded_recovery_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))

            config.ensure_data_directories()

            self.assertTrue((config.recovery_dir / "pending").is_dir())
            self.assertTrue((config.recovery_dir / "failed").is_dir())
            self.assertFalse((config.recovery_dir / "live").exists())
            self.assertFalse((config.recovery_dir / "removed").exists())


if __name__ == "__main__":
    unittest.main()
