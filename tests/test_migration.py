from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from helpers import make_bundle, make_config  # noqa: E402
from vmctl.errors import StateConflictError, TransactionError  # noqa: E402
from vmctl.migration import (  # noqa: E402
    candidate_digest,
    execute_legacy_recovery,
    inventory_legacy_recovery,
    write_inventory_manifest,
)


class LegacyRecoveryMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = make_config(self.root)
        self.removed = make_bundle(
            self.config.recovery_dir / "removed" / "old-snapshot" / "VM.bundle"
        ).parent
        self.live = make_bundle(
            self.config.recovery_dir / "live" / "old-live" / "VM.bundle"
        ).parent
        self.unrelated = make_bundle(
            self.config.recovery_dir / "failed" / "keep" / "VM.bundle"
        ).parent

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def manifest(self) -> tuple[Path, dict]:
        path = self.root / "legacy-manifest.json"
        inventory = inventory_legacy_recovery(self.config)
        write_inventory_manifest(path, inventory)
        return path, inventory

    def test_inventory_lists_exact_candidates_without_deleting(self) -> None:
        inventory = inventory_legacy_recovery(self.config)

        self.assertEqual(inventory["entryCount"], 2)
        self.assertEqual(
            {candidate["category"] for candidate in inventory["candidates"]},
            {"live", "removed"},
        )
        self.assertTrue(all(candidate["logicalBytes"] > 0 for candidate in inventory["candidates"]))
        self.assertGreater(inventory["diskFreeBytes"], 0)
        self.assertEqual(
            inventory["candidateDigest"], candidate_digest(inventory["candidates"])
        )
        self.assertTrue(self.removed.exists())
        self.assertTrue(self.live.exists())
        self.assertTrue(self.unrelated.exists())

    def test_execution_requires_matching_reviewed_digest(self) -> None:
        path, inventory = self.manifest()

        with self.assertRaises(TransactionError):
            execute_legacy_recovery(
                self.config,
                path,
                approved_digest="not-reviewed",
            )

        self.assertTrue(self.removed.exists())
        self.assertTrue(self.live.exists())
        self.assertEqual(inventory["entryCount"], 2)

    def test_execution_refuses_running_vm(self) -> None:
        path, inventory = self.manifest()

        with self.assertRaises(StateConflictError):
            execute_legacy_recovery(
                self.config,
                path,
                approved_digest=inventory["candidateDigest"],
                vm_running=True,
            )

        self.assertTrue(self.removed.exists())

    def test_execution_refuses_changed_candidate_set(self) -> None:
        path, inventory = self.manifest()
        make_bundle(
            self.config.recovery_dir / "removed" / "new-after-review" / "VM.bundle"
        )

        with self.assertRaises(TransactionError):
            execute_legacy_recovery(
                self.config,
                path,
                approved_digest=inventory["candidateDigest"],
            )

        self.assertTrue(self.removed.exists())

    def test_execution_refuses_symlink_candidate(self) -> None:
        outside = make_bundle(self.root / "outside" / "VM.bundle").parent
        link = self.config.recovery_dir / "removed" / "linked"
        link.symlink_to(outside, target_is_directory=True)
        path, inventory = self.manifest()

        with self.assertRaises(TransactionError):
            execute_legacy_recovery(
                self.config,
                path,
                approved_digest=inventory["candidateDigest"],
            )

        self.assertTrue(outside.exists())
        self.assertTrue(link.is_symlink())

    def test_execution_refuses_manifest_path_escape_even_with_recomputed_digest(self) -> None:
        path, inventory = self.manifest()
        outside = make_bundle(self.root / "outside" / "VM.bundle").parent
        inventory["candidates"][0]["path"] = str(outside)
        inventory["candidateDigest"] = candidate_digest(inventory["candidates"])
        path.write_text(json.dumps(inventory))

        with self.assertRaises(TransactionError):
            execute_legacy_recovery(
                self.config,
                path,
                approved_digest=inventory["candidateDigest"],
            )

        self.assertTrue(outside.exists())

    def test_execution_refuses_live_bundle_candidate(self) -> None:
        path, inventory = self.manifest()
        protected_config = replace(self.config, live_bundle=self.live)

        with self.assertRaises(StateConflictError):
            execute_legacy_recovery(
                protected_config,
                path,
                approved_digest=inventory["candidateDigest"],
            )

        self.assertTrue(self.live.exists())

    def test_execution_deletes_only_reviewed_legacy_candidates(self) -> None:
        path, inventory = self.manifest()

        result = execute_legacy_recovery(
            self.config,
            path,
            approved_digest=inventory["candidateDigest"],
        )

        self.assertEqual(result["deletedEntries"], 2)
        self.assertIn("diskFreeBytesBefore", result)
        self.assertIn("diskFreeBytesAfter", result)
        self.assertFalse(self.removed.exists())
        self.assertFalse(self.live.exists())
        self.assertTrue(self.unrelated.exists())


if __name__ == "__main__":
    unittest.main()
