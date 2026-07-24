from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import subprocess
from pathlib import Path

from helpers import make_bundle
from vmctl.catalog import Catalog
from vmctl.config import Config
from vmctl.errors import StateConflictError, UsageError
from vmctl.initialization import import_bundle, install_bundle
from vmctl.migration import apply_migration_plan, create_migration_plan
from vmctl.network import validate_mac
from vmctl.redaction import redact_text
from vmctl.preflight import run_preflight
from vmctl.store import atomic_write_json
from vmctl.uninstall import uninstall


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def installed_config(root: Path) -> Config:
    install_root = root / "Library/Application Support/vmctl"
    return Config(
        project_root=root / "source",
        live_bundle=install_root / "data/live/VM.bundle",
        app_bundle=install_root / "current/libexec/VMRunner.app",
        snapshot_dir=install_root / "data/snapshots",
        recovery_dir=install_root / "data/recovery",
        state_dir=install_root / "data/state",
        launcher_path=root / ".local/bin/vmctl",
        config_file=install_root / "config.json",
    )


class InitializationTests(unittest.TestCase):
    def test_clone_preview_is_non_mutating_then_creates_private_managed_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = installed_config(root)
            source = make_bundle(root / "imports/VM.bundle")
            (source / "NetworkMACAddress").write_text("02:11:22:33:44:55\n")
            output = io.StringIO()

            with self.assertRaises(StateConflictError):
                import_bundle(config, [str(source)], stdout=output)
            self.assertFalse(config.live_bundle.exists())
            self.assertFalse(config.state_dir.exists())
            self.assertEqual(
                (source / "NetworkMACAddress").read_text().strip(),
                "02:11:22:33:44:55",
            )

            import_bundle(config, [str(source), "--yes"], stdout=io.StringIO())
            self.assertTrue(config.live_bundle.is_dir())
            self.assertEqual(Catalog(config).get_base(), "initial")
            managed_mac = (config.live_bundle / "NetworkMACAddress").read_text().strip()
            validate_mac(managed_mac)
            self.assertNotEqual(managed_mac, "02:11:22:33:44:55")
            self.assertEqual(
                (source / "NetworkMACAddress").read_text().strip(),
                "02:11:22:33:44:55",
            )
            self.assertEqual(config.live_bundle.stat().st_mode & 0o077, 0)
            self.assertEqual(config.config_file.stat().st_mode & 0o077, 0)

    def test_suspended_import_requires_explicit_clone_only_discard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = installed_config(root)
            source = make_bundle(root / "imports/VM.bundle", suspended=True)

            with self.assertRaises(StateConflictError):
                import_bundle(config, [str(source)], stdout=io.StringIO())
            self.assertTrue((source / "SaveFile.vzvmsave").is_file())
            self.assertFalse(config.live_bundle.exists())

            with self.assertRaises(UsageError):
                import_bundle(
                    config,
                    [
                        str(source),
                        "--mode",
                        "adopt",
                        "--discard-saved-state",
                    ],
                    stdout=io.StringIO(),
                )

            preview = io.StringIO()
            with self.assertRaises(StateConflictError):
                import_bundle(
                    config,
                    [str(source), "--discard-saved-state"],
                    stdout=preview,
                )
            self.assertIn("Saved state: discard from clone", preview.getvalue())
            self.assertTrue((source / "SaveFile.vzvmsave").is_file())
            self.assertFalse(config.live_bundle.exists())

            import_bundle(
                config,
                [str(source), "--discard-saved-state", "--yes"],
                stdout=io.StringIO(),
            )
            self.assertTrue((source / "SaveFile.vzvmsave").is_file())
            self.assertFalse((config.live_bundle / "SaveFile.vzvmsave").exists())
            self.assertFalse(
                (config.snapshot_dir / "initial/VM.bundle/SaveFile.vzvmsave").exists()
            )

    def test_fake_local_restore_install_stages_then_initializes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = installed_config(root)
            helper = config.app_bundle / "Contents/Helpers/VMInstaller"
            helper.parent.mkdir(parents=True)
            helper.write_text(
                "#!/bin/sh\n"
                "bundle=''\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  if [ \"$1\" = '--bundle' ]; then bundle=\"$2\"; shift 2; else shift; fi\n"
                "done\n"
                "mkdir -p \"$bundle\"\n"
                "for item in Disk.img AuxiliaryStorage HardwareModel MachineIdentifier; do\n"
                "  printf 'fixture' > \"$bundle/$item\"\n"
                "done\n"
                "printf '02:aa:bb:cc:dd:ee\\n' > \"$bundle/NetworkMACAddress\"\n"
                "printf '%s\\n' '{\"schemaVersion\":1,\"event\":\"complete\",\"fractionCompleted\":1}'\n",
                encoding="utf-8",
            )
            helper.chmod(0o755)
            restore = root / "restore.ipsw"
            restore.write_bytes(b"fixture restore")
            arguments = ["--restore", str(restore)]

            with self.assertRaises(StateConflictError):
                install_bundle(config, arguments, stdout=io.StringIO())
            self.assertFalse(config.live_bundle.exists())

            install_bundle(config, [*arguments, "--yes"], stdout=io.StringIO())
            self.assertTrue(config.live_bundle.is_dir())
            self.assertEqual(Catalog(config).get_base(), "initial")
            self.assertTrue(restore.is_file())


class MigrationTests(unittest.TestCase):
    def test_plan_and_apply_adopt_paths_without_moving_or_deleting_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = installed_config(root)
            make_bundle(config.live_bundle)
            make_bundle(config.snapshot_dir / "initial/VM.bundle")
            Catalog(config).initialize_baseline("initial")
            marker = config.live_bundle / "Disk.img"
            before = marker.read_bytes()

            plan = create_migration_plan(config)
            manifest = root / "migration.json"
            atomic_write_json(manifest, plan)
            result = apply_migration_plan(
                config,
                manifest,
                approved_digest=str(plan["candidateDigest"]),
                vm_running=False,
            )

            self.assertEqual(result["dataMovement"], "none")
            self.assertEqual(result["deletions"], [])
            self.assertEqual(marker.read_bytes(), before)
            self.assertEqual(
                Path(json.loads(config.config_file.read_text())["liveBundle"]),
                config.live_bundle.resolve(),
            )

    def test_changed_or_unapproved_plan_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = installed_config(root)
            make_bundle(config.live_bundle)
            make_bundle(config.snapshot_dir / "initial/VM.bundle")
            Catalog(config).initialize_baseline("initial")
            plan = create_migration_plan(config)
            manifest = root / "migration.json"
            atomic_write_json(manifest, plan)
            with self.assertRaises(Exception):
                apply_migration_plan(
                    config,
                    manifest,
                    approved_digest="wrong",
                    vm_running=False,
                )


class UninstallTests(unittest.TestCase):
    def _installation(self, root: Path) -> Config:
        config = installed_config(root)
        install_root = config.config_file.parent
        release = install_root / "releases/0.1.0"
        binary = release / "bin/vmctl"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n")
        current = install_root / "current"
        current.symlink_to("releases/0.1.0")
        config.launcher_path.parent.mkdir(parents=True)
        config.launcher_path.symlink_to(current / "bin/vmctl")
        make_bundle(config.live_bundle)
        atomic_write_json(
            install_root / "install-manifest.json",
            {
                "schemaVersion": 1,
                "installRoot": str(install_root),
                "launcher": str(config.launcher_path),
                "activeVersion": "0.1.0",
                "ownedProgramPaths": [
                    str(current),
                    str(install_root / "releases"),
                    str(config.launcher_path),
                ],
                "ownedDataPaths": [],
            },
        )
        return config

    def test_default_uninstall_preserves_vm_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._installation(Path(temporary))
            disk = config.live_bundle / "Disk.img"
            before = disk.read_bytes()
            result = uninstall(config, [], vm_running=False)
            self.assertIn("preserved", result.lower())
            self.assertEqual(disk.read_bytes(), before)
            self.assertFalse(config.launcher_path.exists())
            self.assertFalse((config.config_file.parent / "releases").exists())

    def test_purge_requires_exact_path_and_stopped_vm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._installation(Path(temporary))
            data_root = config.config_file.parent / "data"
            with self.assertRaises(StateConflictError):
                uninstall(
                    config,
                    ["--purge-data", "--approve-path", str(data_root)],
                    vm_running=True,
                )
            with self.assertRaises(StateConflictError):
                uninstall(
                    config,
                    ["--purge-data", "--approve-path", str(data_root.parent)],
                    vm_running=False,
                )

    def test_exact_approved_purge_removes_only_portable_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._installation(Path(temporary))
            data_root = config.config_file.parent / "data"
            sentinel = config.config_file.parent / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            result = uninstall(
                config,
                ["--purge-data", "--approve-path", str(data_root)],
                vm_running=False,
            )
            self.assertIn("permanently purged", result.lower())
            self.assertFalse(data_root.exists())
            self.assertEqual(sentinel.read_text(), "keep")


class RedactionTests(unittest.TestCase):
    def test_share_redaction_removes_paths_user_and_terminal_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = installed_config(Path(temporary))
            value = f"{config.live_bundle}\n{os.environ.get('USER', '')}\x1b[31m"
            redacted = redact_text(value, config)
            self.assertNotIn(str(config.live_bundle), redacted)
            if os.environ.get("USER"):
                self.assertNotIn(os.environ["USER"], redacted)
            self.assertNotIn("\x1b", redacted)
            self.assertIn("<live-vm>", redacted)


class PreflightTests(unittest.TestCase):
    def test_missing_tools_reports_walkthrough_without_creating_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "install"
            data = root / "data"
            launcher = root / "bin/vmctl"

            def fake_run(arguments, **kwargs):
                if arguments[0] == "/bin/df":
                    return subprocess.CompletedProcess(
                        arguments, 0, "Filesystem Mounted on\n/dev/test /\n", ""
                    )
                if arguments[0] == "/usr/sbin/diskutil":
                    return subprocess.CompletedProcess(
                        arguments, 0, "File System Personality: APFS\n", ""
                    )
                return subprocess.CompletedProcess(arguments, 1, "", "missing")

            checks = run_preflight(
                source_root=PROJECT_ROOT,
                install_root=install,
                data_root=data,
                launcher=launcher,
                run=fake_run,
            )
            command_line_tools = next(
                check for check in checks if check.name == "Command Line Tools"
            )
            self.assertEqual(command_line_tools.level, "FAIL")
            self.assertIn("xcode-select --install", command_line_tools.next_action or "")
            self.assertFalse(install.exists())
            self.assertFalse(data.exists())
            self.assertFalse(launcher.parent.exists())


if __name__ == "__main__":
    unittest.main()
