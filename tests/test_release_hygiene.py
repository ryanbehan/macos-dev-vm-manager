from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCANNER = PROJECT_ROOT / "script/check_release_hygiene.py"


class ProvenanceTests(unittest.TestCase):
    def test_adapted_files_have_notice_and_license_is_present(self) -> None:
        adapted = [
            "runner/Sources/VMRunner/AppDelegate.swift",
            "runner/Sources/VMRunner/VMConfigurationBuilder.swift",
            "runner/Sources/VMRunner/VMDelegate.swift",
            "runner/Sources/VMRunner/VMPaths.swift",
            "runner/Sources/VMInstaller/main.swift",
            "runner/VMRunner.entitlements",
            "runner/VMInstaller.entitlements",
        ]
        notice = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        apple_license = (
            PROJECT_ROOT / "LICENSES/Apple-Sample-Code-MIT.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("c8bf24264607633b6dbdf242cf610f9a", notice)
        self.assertIn("Copyright © 2025 Apple Inc.", apple_license)
        for relative in adapted:
            with self.subTest(relative=relative):
                self.assertIn(f"`{relative}`", notice)
                self.assertIn(
                    "THIRD_PARTY_NOTICES.md",
                    (PROJECT_ROOT / relative).read_text(encoding="utf-8"),
                )


class HygieneScannerTests(unittest.TestCase):
    def _repository(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "README.md").write_text("portable source\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)

    def _scan(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(SCANNER),
                "--root",
                str(root),
                "--allow-author",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_clean_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._repository(root)
            self.assertEqual(self._scan(root).returncode, 0)

    def test_extracted_source_passes_without_git_and_ignores_build_products(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("portable source\n", encoding="utf-8")
            generated = root / "runner/.build"
            generated.mkdir(parents=True)
            (generated / "VMRunner").write_bytes(b"\0" * 1_048_577)
            cache = root / "src/vmctl/__pycache__"
            cache.mkdir(parents=True)
            (cache / "module.pyc").write_bytes(b"\0generated")

            self.assertEqual(self._scan(root).returncode, 0)

    def test_extracted_source_still_scans_unexpected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private_path = "/" + "Users" + "/example/private"
            (root / "private.txt").write_text(
                f"development path {private_path}\n", encoding="utf-8"
            )

            result = self._scan(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("absolute macOS home path", result.stderr)

    def test_personal_path_and_force_added_vm_artifact_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._repository(root)
            private_path = "/" + "Users" + "/example/private"
            (root / "private.txt").write_text(
                f"development path {private_path}\n", encoding="utf-8"
            )
            (root / "Disk.img").write_bytes(b"not a real disk")
            subprocess.run(
                ["git", "-C", str(root), "add", "-f", "private.txt", "Disk.img"],
                check=True,
            )
            result = self._scan(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("absolute macOS home path", result.stderr)
            self.assertIn("prohibited VM", result.stderr)


if __name__ == "__main__":
    unittest.main()
