from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from helpers import make_bundle, make_config  # noqa: E402
from vmctl.catalog import Catalog  # noqa: E402
from vmctl.errors import StateConflictError, TransactionError  # noqa: E402
from vmctl.transactions import (  # noqa: E402
    begin_transaction,
    read_transaction,
    reconcile_transaction,
    set_transaction_phase,
)


class TransactionJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = make_config(self.root)
        self.config.ensure_data_directories()
        self.catalog = Catalog(self.config)
        self.live = make_bundle(self.config.live_bundle, marker="old-live")
        self.source = make_bundle(
            self.config.snapshot_dir / "source" / "VM.bundle", marker="source"
        )
        self.catalog.write_snapshot_metadata(
            self.source.parent,
            name="source",
            parent=None,
            captured_state="shutdown",
        )
        self.catalog.set_live_origin("source")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def paths(self, identifier: str = "abc123") -> tuple[Path, Path]:
        temporary_live = self.config.live_bundle.parent / (
            f".{self.config.live_bundle.name}.vmctl-{identifier}"
        )
        rollback = (
            self.config.recovery_dir
            / "pending"
            / identifier
            / "VM.bundle"
        )
        return temporary_live, rollback

    def begin(self, identifier: str = "abc123") -> tuple[Path, Path]:
        temporary_live, rollback = self.paths(identifier)
        begin_transaction(
            self.config,
            identifier=identifier,
            operation="load",
            source_snapshot="source",
            temporary_live=temporary_live,
            rollback_bundle=rollback,
        )
        return temporary_live, rollback

    def test_journal_records_atomic_phase_transitions(self) -> None:
        temporary_live, rollback = self.begin()
        self.assertEqual(read_transaction(self.config)["phase"], "prepared")
        for phase in ("displaced", "activated", "committed"):
            journal = set_transaction_phase(self.config, phase)
            self.assertEqual(journal["phase"], phase)
            self.assertEqual(read_transaction(self.config), journal)
        self.assertEqual(journal["temporaryLive"], str(temporary_live))
        self.assertEqual(journal["rollbackBundle"], str(rollback))

    def test_prepared_reconciliation_discards_clone_only(self) -> None:
        temporary_live, _ = self.begin()
        shutil.copytree(self.source, temporary_live)
        old_marker = (self.live / "Disk.img").read_bytes()

        result = reconcile_transaction(self.config, self.catalog)

        self.assertEqual(result, "rolled-back")
        self.assertFalse(temporary_live.exists())
        self.assertFalse(self.config.transaction_file.exists())
        self.assertEqual((self.live / "Disk.img").read_bytes(), old_marker)

    def test_displaced_reconciliation_restores_old_live(self) -> None:
        temporary_live, rollback = self.begin()
        shutil.copytree(self.source, temporary_live)
        rollback.parent.mkdir(parents=True)
        self.live.rename(rollback)
        set_transaction_phase(self.config, "displaced")

        result = reconcile_transaction(self.config, self.catalog)

        self.assertEqual(result, "rolled-back")
        self.assertIn(b"old-live", (self.config.live_bundle / "Disk.img").read_bytes())
        self.assertFalse(temporary_live.exists())
        self.assertFalse((self.config.recovery_dir / "pending" / "abc123").exists())
        self.assertFalse(self.config.transaction_file.exists())

    def test_activated_reconciliation_replaces_new_live_with_old_live(self) -> None:
        temporary_live, rollback = self.begin()
        shutil.copytree(self.source, temporary_live)
        rollback.parent.mkdir(parents=True)
        self.live.rename(rollback)
        temporary_live.rename(self.config.live_bundle)
        set_transaction_phase(self.config, "activated")

        result = reconcile_transaction(self.config, self.catalog)

        self.assertEqual(result, "rolled-back")
        self.assertIn(b"old-live", (self.config.live_bundle / "Disk.img").read_bytes())
        self.assertFalse(temporary_live.exists())
        self.assertFalse(self.config.transaction_file.exists())

    def test_committed_reconciliation_keeps_live_and_deletes_rollback(self) -> None:
        temporary_live, rollback = self.begin()
        rollback.parent.mkdir(parents=True)
        self.live.rename(rollback)
        shutil.copytree(self.source, self.config.live_bundle)
        self.catalog.set_live_origin("source")
        set_transaction_phase(self.config, "committed")

        result = reconcile_transaction(self.config, self.catalog)

        self.assertEqual(result, "committed-cleanup")
        self.assertIn(b"source", (self.config.live_bundle / "Disk.img").read_bytes())
        self.assertFalse((self.config.recovery_dir / "pending" / "abc123").exists())
        self.assertFalse(self.config.transaction_file.exists())

    def test_running_vm_blocks_reconciliation_without_changing_data(self) -> None:
        temporary_live, _ = self.begin()
        shutil.copytree(self.source, temporary_live)

        with self.assertRaises(StateConflictError):
            reconcile_transaction(self.config, self.catalog, vm_running=True)

        self.assertTrue(temporary_live.exists())
        self.assertTrue(self.config.transaction_file.exists())

    def test_missing_rollback_is_quarantined_as_failed_transaction(self) -> None:
        self.begin()
        self.config.live_bundle.rename(self.root / "unexpected-live-location")
        set_transaction_phase(self.config, "displaced")

        with self.assertRaises(TransactionError):
            reconcile_transaction(self.config, self.catalog)

        self.assertFalse(self.config.transaction_file.exists())
        failures = list((self.config.recovery_dir / "failed").glob("*--transaction-abc123"))
        self.assertEqual(len(failures), 1)
        self.assertTrue((failures[0] / "failure.json").is_file())

    def test_invalid_journal_paths_are_quarantined_without_touching_outside(self) -> None:
        outside = make_bundle(self.root / "outside" / "VM.bundle")
        _, rollback = self.paths()
        begin_transaction(
            self.config,
            identifier="abc123",
            operation="load",
            source_snapshot="source",
            temporary_live=outside,
            rollback_bundle=rollback,
        )

        with self.assertRaises(TransactionError):
            reconcile_transaction(self.config, self.catalog)

        self.assertTrue(outside.exists())
        self.assertFalse(self.config.transaction_file.exists())


if __name__ == "__main__":
    unittest.main()
