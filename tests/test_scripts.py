from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import make_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class InstallerScriptTests(unittest.TestCase):
    def test_legacy_entry_point_delegates_to_source_installer(self) -> None:
        text = (PROJECT_ROOT / "script/install.sh").read_text(encoding="utf-8")
        self.assertIn("install-from-source.sh", text)
        self.assertNotIn("VMCTL_BASELINE_NAME", text)


class BuildRunnerScriptTests(unittest.TestCase):
    def prepare_environment(self, root: Path, *, entitlement: bool = True) -> dict[str, str]:
        runner = root / "runner"
        runner.mkdir()
        shutil.copy2(PROJECT_ROOT / "runner" / "VMRunner.entitlements", runner)
        shutil.copy2(PROJECT_ROOT / "runner" / "VMInstaller.entitlements", runner)
        (root / "VERSION").write_text("0.1.0\n")
        (root / "script").mkdir()
        shutil.copy2(PROJECT_ROOT / "script" / "verify_app.py", root / "script")
        bin_dir = root / "fake-bin"
        bin_dir.mkdir()
        output = root / "build"
        output.mkdir()
        executable(output / "VMRunner", "#!/bin/sh\nexit 0\n")
        executable(
            output / "VMInstaller",
            "#!/bin/sh\n"
            "if [ \"${1:-}\" = \"--version\" ]; then "
            "echo '0.1.0 protocol=1'; fi\n"
            "exit 0\n",
        )
        executable(
            bin_dir / "swift",
            f"#!/bin/sh\ncase \"$*\" in *--show-bin-path*) echo '{output}' ;; esac\n",
        )
        executable(
            bin_dir / "security",
            "#!/bin/sh\necho '  1) ABCD \"Example Signing Identity\"'\n",
        )
        executable(bin_dir / "strip", "#!/bin/sh\nexit 0\n")
        entitlement_xml = (
            "<?xml version=\"1.0\"?><plist><dict><key>com.apple.security.virtualization</key><true/></dict></plist>"
            if entitlement
            else "<?xml version=\"1.0\"?><plist><dict></dict></plist>"
        )
        executable(
            bin_dir / "codesign",
            f"#!/bin/sh\ncase \"$*\" in *--entitlements\\ :-*) echo '{entitlement_xml}' >&2 ;; esac\n",
        )
        return {
            **os.environ,
            "VMCTL_PROJECT_ROOT": str(root),
            "VMCTL_APP_BUNDLE": str(root / "app" / "VMRunner.app"),
            "VMCTL_SWIFT_BIN": str(bin_dir / "swift"),
            "VMCTL_SECURITY_BIN": str(bin_dir / "security"),
            "VMCTL_STRIP_BIN": str(bin_dir / "strip"),
            "VMCTL_CODESIGN_BIN": str(bin_dir / "codesign"),
        }

    def run_builder(self, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PROJECT_ROOT / "script" / "build_runner.sh")],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_stages_runner_with_verified_entitlement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.prepare_environment(root)
            result = self.run_builder(environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "app/VMRunner.app/Contents/MacOS/VMRunner").is_file())

    def test_rejects_missing_identity_missing_executable_and_entitlement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.prepare_environment(root)
            environment["VMCTL_CODESIGN_IDENTITY"] = "Unavailable"
            environment["VMCTL_SIGNING_MODE"] = "development"
            self.assertIn("unavailable", self.run_builder(environment).stderr)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.prepare_environment(root)
            (root / "build/VMRunner").unlink()
            self.assertIn("missing", self.run_builder(environment).stderr)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.prepare_environment(root, entitlement=False)
            self.assertIn("virtualization", self.run_builder(environment).stderr.lower())

    def test_rejects_signing_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.prepare_environment(root)
            executable(Path(environment["VMCTL_CODESIGN_BIN"]), "#!/bin/sh\nexit 9\n")
            self.assertNotEqual(self.run_builder(environment).returncode, 0)


if __name__ == "__main__":
    unittest.main()
