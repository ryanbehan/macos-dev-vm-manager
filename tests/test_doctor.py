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
from vmctl.doctor import run_checks  # noqa: E402


class DoctorTests(unittest.TestCase):
    def test_doctor_aggregates_failures_without_creating_runner_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            make_bundle(config.live_bundle)
            baseline = config.snapshot_dir / "baseline" / "VM.bundle"
            shutil.copytree(config.live_bundle, baseline)
            Catalog(config).initialize_baseline("baseline")

            checks = run_checks(config)

            names = {check.name for check in checks}
            self.assertIn("platform", names)
            self.assertIn("architecture", names)
            self.assertIn("live bundle", names)
            self.assertIn("base snapshot", names)
            self.assertIn("snapshot directory", names)
            self.assertIn("runner signature", names)
            self.assertIn("virtualization entitlement", names)
            self.assertIn("runner quarantine", names)
            self.assertIn("transaction state", names)
            self.assertIn("pending rollback", names)
            self.assertIn("failed recovery", names)
            self.assertIn("legacy recovery", names)
            self.assertIn("data filesystem", names)
            self.assertFalse(config.app_bundle.exists())
            self.assertFalse((config.recovery_dir / "live").exists())
            self.assertFalse((config.recovery_dir / "removed").exists())


if __name__ == "__main__":
    unittest.main()
