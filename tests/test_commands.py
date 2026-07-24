from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from helpers import FakeLifecycle, make_bundle, make_config  # noqa: E402
from vmctl.catalog import Catalog  # noqa: E402
from vmctl.cli import main  # noqa: E402
from vmctl.commands import Commands  # noqa: E402
from vmctl.transactions import begin_transaction  # noqa: E402
from vmctl.transactions import set_transaction_phase as real_set_transaction_phase  # noqa: E402


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = make_config(self.root)
        self.config.ensure_data_directories()
        make_bundle(self.config.live_bundle, suspended=True, marker="live")
        baseline_bundle = self.config.snapshot_dir / "baseline" / "VM.bundle"
        shutil.copytree(self.config.live_bundle, baseline_bundle)
        self.catalog = Catalog(self.config)
        self.catalog.initialize_baseline("baseline")
        self.lifecycle = FakeLifecycle()
        self.handlers = Commands(
            self.config, catalog=self.catalog, lifecycle=self.lifecycle
        ).handlers()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        result = main(
            list(arguments),
            handlers=self.handlers,
            stdout=stdout,
            stderr=stderr,
        )
        return result, stdout.getvalue(), stderr.getvalue()

    def test_snapshot_list_tree_and_load(self) -> None:
        result, output, error = self.invoke("snapshot", "dev-ready")
        self.assertEqual(result, 0, error)
        snapshot = self.catalog.get("dev-ready")
        self.assertEqual(snapshot.parent, "baseline")

        result, output, error = self.invoke("list")
        self.assertEqual(result, 0, error)
        self.assertIn("baseline", output)
        self.assertIn("dev-ready", output)

        (self.config.live_bundle / "Disk.img").write_bytes(b"changed-live")
        result, output, error = self.invoke("load", "dev-ready")
        self.assertEqual(result, 0, error)
        self.assertEqual(
            (self.config.live_bundle / "Disk.img").read_bytes(),
            (self.catalog.snapshot_bundle("dev-ready") / "Disk.img").read_bytes(),
        )
        self.assertFalse(any((self.config.recovery_dir / "pending").glob("*")))
        self.assertFalse(self.config.transaction_file.exists())
        self.assertFalse(any((self.config.recovery_dir / "live").glob("*/VM.bundle")))

    def test_remove_permanently_deletes_snapshot(self) -> None:
        self.assertEqual(self.invoke("snapshot", "throwaway")[0], 0)
        result, output, error = self.invoke("remove", "throwaway")
        self.assertEqual(result, 0, error)
        self.assertFalse(self.catalog.snapshot_directory("throwaway").exists())
        self.assertIn("permanently", output)
        self.assertIn(str(self.catalog.snapshot_directory("throwaway")), output)
        self.assertFalse((self.config.recovery_dir / "removed").exists())
        self.assertEqual(self.invoke("undelete", "throwaway")[0], 2)

    def test_base_is_protected_and_promotion_is_atomic(self) -> None:
        result, _, error = self.invoke("remove", "baseline")
        self.assertEqual(result, 3)
        self.assertIn("base snapshot", error)

        self.assertEqual(self.invoke("snapshot", "candidate")[0], 0)
        self.assertEqual(self.invoke("promote", "candidate")[0], 0)
        self.assertEqual(self.catalog.get_base(), "candidate")
        self.assertEqual(self.catalog.get("baseline").name, "baseline")

    def test_commit_creates_snapshot_and_promotes_it(self) -> None:
        result, output, error = self.invoke("commit", "committed")
        self.assertEqual(result, 0, error)
        self.assertEqual(self.catalog.get_base(), "committed")
        self.assertEqual(self.catalog.get("committed").name, "committed")

    def test_failed_commit_promotion_preserves_old_base_and_deletes_snapshot(self) -> None:
        with patch.object(self.catalog, "set_base", side_effect=RuntimeError("injected")):
            result, output, error = self.invoke("commit", "failed-commit")
        self.assertEqual(result, 6, error)
        self.assertEqual(self.catalog.get_base(), "baseline")
        self.assertFalse(self.catalog.snapshot_directory("failed-commit").exists())
        self.assertFalse((self.config.recovery_dir / "removed").exists())
        self.assertFalse(any((self.config.recovery_dir / "failed").iterdir()))

    def test_failed_commit_preserves_snapshot_only_when_cleanup_fails(self) -> None:
        with (
            patch.object(self.catalog, "set_base", side_effect=RuntimeError("injected")),
            patch(
                "vmctl.commands.permanent_delete_tree",
                side_effect=RuntimeError("injected cleanup failure"),
            ),
        ):
            result, output, error = self.invoke("commit", "failed-cleanup")

        self.assertEqual(result, 6, error)
        self.assertEqual(self.catalog.get_base(), "baseline")
        self.assertFalse(self.catalog.snapshot_directory("failed-cleanup").exists())
        failed = list(
            (self.config.recovery_dir / "failed").glob(
                "*--failed-commit-failed-cleanup"
            )
        )
        self.assertEqual(len(failed), 1)
        self.assertTrue((failed[0] / "VM.bundle").is_dir())
        self.assertIn("preserved", output)

    def test_running_vm_blocks_snapshot_and_load(self) -> None:
        self.lifecycle.running = True
        self.assertEqual(self.invoke("snapshot", "blocked")[0], 3)
        self.assertEqual(self.invoke("load", "baseline")[0], 3)

    def test_failed_snapshot_disposes_partial_clone(self) -> None:
        def fail_after_partial_clone(source: Path, destination: Path) -> None:
            destination.mkdir(parents=True)
            (destination / "partial").write_text("preserve me")
            raise RuntimeError("injected clone failure")

        with patch("vmctl.commands.clone_bundle", side_effect=fail_after_partial_clone):
            result, output, error = self.invoke("snapshot", "broken")
        self.assertEqual(result, 6, error)
        self.assertNotIn("preserved", output)
        self.assertFalse(any((self.config.recovery_dir / "failed").iterdir()))
        self.assertFalse(any(self.config.snapshot_dir.glob(".tmp-broken-*")))

    def test_failed_snapshot_preserves_partial_only_when_cleanup_fails(self) -> None:
        def fail_after_partial_clone(source: Path, destination: Path) -> None:
            destination.mkdir(parents=True)
            (destination / "partial").write_text("preserve me")
            raise RuntimeError("injected clone failure")

        with (
            patch("vmctl.commands.clone_bundle", side_effect=fail_after_partial_clone),
            patch(
                "vmctl.commands.permanent_delete_tree",
                side_effect=RuntimeError("injected cleanup failure"),
            ),
        ):
            result, output, error = self.invoke("snapshot", "broken-cleanup")

        self.assertEqual(result, 6, error)
        self.assertIn("preserved", output)
        failed = list(
            (self.config.recovery_dir / "failed").glob("*--snapshot-broken-cleanup")
        )
        self.assertEqual(len(failed), 1)
        self.assertTrue((failed[0] / "VM.bundle/partial").is_file())

    def test_load_rolls_back_if_activation_fails(self) -> None:
        original = (self.config.live_bundle / "Disk.img").read_bytes()
        real_replace = __import__("os").replace

        def fail_live_activation(source: Path, destination: Path) -> None:
            if destination == self.config.live_bundle and source.name.startswith(".VM.bundle.vmctl-"):
                raise OSError("injected activation failure")
            real_replace(source, destination)

        with patch("vmctl.commands.os.replace", side_effect=fail_live_activation):
            result, output, error = self.invoke("load", "baseline")
        self.assertEqual(result, 6, error)
        self.assertEqual((self.config.live_bundle / "Disk.img").read_bytes(), original)
        self.assertIn("restored", output)
        self.assertFalse(any((self.config.recovery_dir / "pending").glob("*")))
        self.assertFalse(self.config.transaction_file.exists())

    def test_revert_and_reset_use_bounded_transactions(self) -> None:
        self.assertEqual(self.invoke("snapshot", "revert-source")[0], 0)
        stored_before = (self.catalog.snapshot_bundle("revert-source") / "Disk.img").read_bytes()
        (self.config.live_bundle / "Disk.img").write_bytes(b"changed")

        result, _, error = self.invoke("revert", "revert-source")
        self.assertEqual(result, 0, error)
        self.assertEqual(
            (self.config.live_bundle / "Disk.img").read_bytes(), stored_before
        )
        self.assertEqual(
            (self.catalog.snapshot_bundle("revert-source") / "Disk.img").read_bytes(),
            stored_before,
        )

        (self.config.live_bundle / "Disk.img").write_bytes(b"changed-again")
        result, _, error = self.invoke("reset")
        self.assertEqual(result, 0, error)
        self.assertEqual(
            (self.config.live_bundle / "Disk.img").read_bytes(),
            (self.catalog.snapshot_bundle("baseline") / "Disk.img").read_bytes(),
        )
        self.assertFalse(any((self.config.recovery_dir / "pending").glob("*")))
        self.assertFalse(self.config.transaction_file.exists())

    def test_load_restores_live_origin_if_commit_phase_write_fails(self) -> None:
        self.assertEqual(self.invoke("snapshot", "metadata-source")[0], 0)
        (self.config.live_bundle / "Disk.img").write_bytes(b"old-current-live")

        def fail_commit_phase(config, phase):
            if phase == "committed":
                raise RuntimeError("injected committed journal failure")
            return real_set_transaction_phase(config, phase)

        with patch("vmctl.commands.set_transaction_phase", side_effect=fail_commit_phase):
            result, output, error = self.invoke("load", "metadata-source")

        self.assertEqual(result, 6, error)
        self.assertIn("restored", output)
        self.assertEqual(
            (self.config.live_bundle / "Disk.img").read_bytes(), b"old-current-live"
        )
        self.assertEqual(self.catalog.live_origin()["sourceSnapshot"], "baseline")
        self.assertFalse(self.config.transaction_file.exists())

    def test_removed_parent_does_not_invalidate_child(self) -> None:
        self.assertEqual(self.invoke("snapshot", "parent")[0], 0)
        self.assertEqual(self.invoke("load", "parent")[0], 0)
        self.assertEqual(self.invoke("snapshot", "child")[0], 0)
        self.assertEqual(self.invoke("load", "baseline")[0], 0)
        self.assertEqual(self.invoke("remove", "parent")[0], 0)
        tree = self.invoke("tree")[1]
        self.assertIn("parent [deleted]", tree)
        self.assertEqual(self.invoke("load", "child")[0], 0)

    def test_detach_live_is_explicit_and_stopped(self) -> None:
        self.assertEqual(self.invoke("snapshot", "source")[0], 0)
        self.assertEqual(self.invoke("load", "source")[0], 0)
        self.assertEqual(self.invoke("remove", "source")[0], 3)
        self.assertEqual(self.invoke("remove", "source", "--detach-live")[0], 0)
        self.assertTrue(self.catalog.live_origin()["detached"])

    def test_list_and_tree_reject_removed_catalog_options(self) -> None:
        self.assertEqual(self.invoke("list", "--all")[0], 2)
        self.assertEqual(self.invoke("tree", "--all")[0], 2)

    def test_mutating_command_reconciles_prepared_transaction_first(self) -> None:
        identifier = "interrupted"
        temporary_live = self.config.live_bundle.parent / (
            f".{self.config.live_bundle.name}.vmctl-{identifier}"
        )
        shutil.copytree(self.catalog.snapshot_bundle("baseline"), temporary_live)
        begin_transaction(
            self.config,
            identifier=identifier,
            operation="load",
            source_snapshot="baseline",
            temporary_live=temporary_live,
            rollback_bundle=(
                self.config.recovery_dir / "pending" / identifier / "VM.bundle"
            ),
        )

        result, output, error = self.invoke("snapshot", "after-reconcile")

        self.assertEqual(result, 0, error)
        self.assertIn("Reconciled interrupted transaction", output)
        self.assertFalse(temporary_live.exists())
        self.assertFalse(self.config.transaction_file.exists())

    def test_status_reports_transaction_and_recovery_storage(self) -> None:
        (self.config.recovery_dir / "failed" / "example").mkdir()
        legacy = self.config.recovery_dir / "live" / "legacy-example"
        legacy.mkdir(parents=True)

        result, output, error = self.invoke("status")

        self.assertEqual(result, 0, error)
        self.assertIn("Transaction: none", output)
        self.assertIn("Pending rollbacks: 0", output)
        self.assertIn("Failed recovery artifacts: 1", output)
        self.assertIn("Legacy recovery entries: 1", output)


if __name__ == "__main__":
    unittest.main()
