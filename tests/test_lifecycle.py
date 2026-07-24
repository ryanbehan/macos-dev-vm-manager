from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import signal
from unittest.mock import patch
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from helpers import make_bundle, make_config  # noqa: E402
from vmctl.lifecycle import LifecycleManager, prepare_local_runner  # noqa: E402
from vmctl.errors import LifecycleError  # noqa: E402
from vmctl.store import atomic_write_json  # noqa: E402


class LifecycleTests(unittest.TestCase):
    def test_running_pid_requires_live_pid_and_runner_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            atomic_write_json(
                config.runtime_file, {"schemaVersion": 1, "pid": 42, "state": "running"}
            )

            def fake_kill(pid: int, signal_number: int) -> None:
                if pid != 42:
                    raise ProcessLookupError

            def fake_run(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    f"{os.geteuid()} {config.runner_executable}\n",
                    "",
                )

            manager = LifecycleManager(config, run=fake_run, kill=fake_kill)
            self.assertEqual(manager.running_pid(), 42)

    def test_stale_runtime_is_reported_but_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            atomic_write_json(
                config.runtime_file, {"schemaVersion": 1, "pid": 99, "state": "running"}
            )

            def missing_process(pid: int, signal_number: int) -> None:
                raise ProcessLookupError

            manager = LifecycleManager(config, kill=missing_process)
            status = manager.status()
            self.assertFalse(status["running"])
            self.assertTrue(status["staleRuntime"])

    def test_runtime_rejects_same_name_wrong_path_uid_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            atomic_write_json(
                config.runtime_file, {"schemaVersion": 1, "pid": 42, "state": "running"}
            )

            def alive(pid: int, signal_number: int) -> None:
                return None

            for output in (
                f"{os.geteuid()} /tmp/VMRunner\n",
                f"{os.geteuid() + 1} {config.runner_executable}\n",
            ):
                with self.subTest(output=output):
                    manager = LifecycleManager(
                        config,
                        run=lambda arguments, **kwargs: subprocess.CompletedProcess(
                            arguments, 0, output, ""
                        ),
                        kill=alive,
                    )
                    self.assertIsNone(manager.running_pid())

            config.runtime_file.chmod(0o644)
            manager = LifecycleManager(config, kill=alive)
            self.assertIsNone(manager.running_pid())

    def test_runtime_rejects_symlinked_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            target = config.state_dir / "target.json"
            atomic_write_json(target, {"pid": 42, "state": "running"})
            config.runtime_file.symlink_to(target)
            manager = LifecycleManager(config, kill=lambda pid, signal_number: None)
            self.assertIsNone(manager.running_pid())

    def test_clean_suspended_runtime_is_not_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            make_bundle(config.live_bundle, suspended=True)
            atomic_write_json(config.runtime_file, {"pid": None, "state": "suspended"})
            status = LifecycleManager(config).status()
            self.assertFalse(status["running"])
            self.assertFalse(status["staleRuntime"])

    def test_start_launches_staged_app_and_observes_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            make_bundle(config.live_bundle)
            config.runner_executable.parent.mkdir(parents=True)
            config.runner_executable.write_bytes(b"runner")
            calls = []

            def fake_run(arguments, **kwargs):
                calls.append(arguments)
                atomic_write_json(config.runtime_file, {"pid": None, "state": "running"})
                return subprocess.CompletedProcess(arguments, 0, "", "")

            prepared = []
            manager = LifecycleManager(
                config,
                run=fake_run,
                kill=lambda pid, sig: None,
                prepare_runner=lambda app: prepared.append(app),
            )
            self.assertEqual(manager.start()["state"], "running")
            self.assertEqual(prepared, [config.app_bundle])
            self.assertEqual(calls[0][0:4], ["/usr/bin/open", "-n", "--arch", "arm64"])

    def test_start_waits_for_restore_to_reach_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            make_bundle(config.live_bundle, suspended=True)
            config.runner_executable.parent.mkdir(parents=True)
            config.runner_executable.write_bytes(b"runner")
            sleep_calls = 0

            def fake_run(arguments, **kwargs):
                atomic_write_json(
                    config.runtime_file, {"pid": 42, "state": "restoring"}
                )
                return subprocess.CompletedProcess(arguments, 0, "", "")

            def fake_sleep(_seconds: float) -> None:
                nonlocal sleep_calls
                sleep_calls += 1
                atomic_write_json(
                    config.runtime_file, {"pid": 42, "state": "running"}
                )

            manager = LifecycleManager(
                config,
                run=fake_run,
                kill=lambda pid, sig: None,
                sleep=fake_sleep,
                prepare_runner=lambda app: None,
            )

            runtime = manager.start()

            self.assertEqual(runtime["state"], "running")
            self.assertEqual(sleep_calls, 1)

    def test_launch_preparation_rejects_quarantine_and_verifies_exact_entitlements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "VMRunner.app"
            app.mkdir()
            calls: list[list[str]] = []

            def fake_run(arguments, **kwargs):
                calls.append(arguments)
                if arguments[1:3] == ["-p", "com.apple.quarantine"]:
                    return subprocess.CompletedProcess(arguments, 1, "", "No such xattr")
                if arguments[1] == "-d":
                    return subprocess.CompletedProcess(
                        arguments,
                        0,
                        "",
                        "<?xml version=\"1.0\"?><plist><dict>"
                        "<key>com.apple.security.virtualization</key><true/>"
                        "</dict></plist>",
                    )
                return subprocess.CompletedProcess(arguments, 0, "", "")

            prepare_local_runner(app, run=fake_run)
            self.assertEqual(
                calls[0],
                ["/usr/bin/xattr", "-p", "com.apple.quarantine", str(app)],
            )
            self.assertIn(
                [
                    "/usr/bin/codesign",
                    "--verify",
                    "--strict",
                    "--deep",
                    str(app),
                ],
                calls,
            )

    def test_launch_preparation_rejects_persistent_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "VMRunner.app"
            app.mkdir()

            def fake_run(arguments, **kwargs):
                if arguments[1:3] == ["-p", "com.apple.quarantine"]:
                    return subprocess.CompletedProcess(arguments, 0, "0081", "")
                return subprocess.CompletedProcess(arguments, 0, "", "")

            with self.assertRaises(LifecycleError):
                prepare_local_runner(app, run=fake_run)

    def test_launch_preparation_rejects_unapproved_entitlement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "VMRunner.app"
            app.mkdir()

            def fake_run(arguments, **kwargs):
                if arguments[1:3] == ["-p", "com.apple.quarantine"]:
                    return subprocess.CompletedProcess(arguments, 1, "", "missing")
                if arguments[1] == "-d":
                    return subprocess.CompletedProcess(
                        arguments,
                        0,
                        "",
                        "<?xml version=\"1.0\"?><plist><dict>"
                        "<key>com.apple.security.virtualization</key><true/>"
                        "<key>com.apple.security.get-task-allow</key><true/>"
                        "</dict></plist>",
                    )
                return subprocess.CompletedProcess(arguments, 0, "", "")

            with self.assertRaises(LifecycleError):
                prepare_local_runner(app, run=fake_run)

    def test_stop_sends_suspend_signal_and_requires_save_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            make_bundle(config.live_bundle)
            atomic_write_json(config.runtime_file, {"pid": 42, "state": "running"})
            alive = True
            signals = []

            def fake_kill(pid: int, signal_number: int) -> None:
                nonlocal alive
                if signal_number == 0 and not alive:
                    raise ProcessLookupError
                if signal_number == signal.SIGUSR2:
                    signals.append(signal_number)
                    (config.live_bundle / "SaveFile.vzvmsave").write_bytes(b"saved")
                    alive = False

            def fake_run(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments, 0, f"{os.geteuid()} {config.runner_executable}\n", ""
                )

            LifecycleManager(config, run=fake_run, kill=fake_kill, sleep=lambda _: None).stop()
            self.assertEqual(signals, [signal.SIGUSR2])

    def test_stop_uses_bounded_timeout_sized_for_large_saved_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            make_bundle(config.live_bundle, suspended=True)
            atomic_write_json(config.runtime_file, {"pid": 42, "state": "running"})

            def fake_kill(pid: int, signal_number: int) -> None:
                return None

            def fake_run(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments, 0, f"{os.geteuid()} {config.runner_executable}\n", ""
                )

            manager = LifecycleManager(config, run=fake_run, kill=fake_kill)
            with patch.object(manager, "_wait_for_exit") as wait_for_exit:
                manager.stop()
            wait_for_exit.assert_called_once_with(42, 180.0)

    def test_shutdown_requires_accepted_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            atomic_write_json(config.runtime_file, {"pid": 42, "state": "running"})
            alive = True

            def fake_kill(pid: int, signal_number: int) -> None:
                nonlocal alive
                if signal_number == 0 and not alive:
                    raise ProcessLookupError
                if signal_number == signal.SIGUSR1:
                    atomic_write_json(config.control_response_file, {"status": "accepted"})
                    alive = False

            def fake_run(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments, 0, f"{os.geteuid()} {config.runner_executable}\n", ""
                )

            LifecycleManager(config, run=fake_run, kill=fake_kill, sleep=lambda _: None).shutdown()

    def test_shutdown_timeout_points_to_guest_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            atomic_write_json(config.runtime_file, {"pid": 42, "state": "running"})

            def fake_kill(pid: int, signal_number: int) -> None:
                if signal_number == signal.SIGUSR1:
                    atomic_write_json(config.control_response_file, {"status": "accepted"})

            def fake_run(arguments, **kwargs):
                return subprocess.CompletedProcess(
                    arguments, 0, f"{os.geteuid()} {config.runner_executable}\n", ""
                )

            manager = LifecycleManager(config, run=fake_run, kill=fake_kill, sleep=lambda _: None)
            with patch.object(manager, "_wait_for_exit", side_effect=LifecycleError("timeout")):
                with self.assertRaises(LifecycleError) as raised:
                    manager.shutdown()
            self.assertIn("shutdown confirmation", raised.exception.hint or "")


if __name__ == "__main__":
    unittest.main()
