from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vmctl.cli import APPROVED_COMMANDS, main  # noqa: E402


class CLIDispatchTests(unittest.TestCase):
    def test_dispatches_registered_handler_and_forwards_arguments(self) -> None:
        calls: list[list[str]] = []

        def status_handler(
            arguments: list[str], stdout: io.StringIO, stderr: io.StringIO
        ) -> int:
            calls.append(arguments)
            stdout.write("status handler\n")
            return 17

        stdout = io.StringIO()
        stderr = io.StringIO()

        result = main(
            ["status", "--json"],
            handlers={"status": status_handler},
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(result, 17)
        self.assertEqual(calls, [["--json"]])
        self.assertEqual(stdout.getvalue(), "status handler\n")
        self.assertEqual(stderr.getvalue(), "")

    def test_top_level_help_lists_every_approved_command(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        result = main(["--help"], stdout=stdout, stderr=stderr)

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        for command in APPROVED_COMMANDS:
            self.assertIn(command, stdout.getvalue())

    def test_no_arguments_show_top_level_help(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        result = main([], stdout=stdout, stderr=stderr)

        self.assertEqual(result, 0)
        self.assertIn("Usage: vmctl", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_unknown_command_returns_usage_error(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        result = main(["not-a-command"], stdout=stdout, stderr=stderr)

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Unknown command: not-a-command", stderr.getvalue())
        self.assertIn("vmctl help", stderr.getvalue())

    def test_known_command_without_implementation_reports_not_ready(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        result = main(["status"], handlers={}, stdout=stdout, stderr=stderr)

        self.assertEqual(result, 4)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("status is not implemented yet", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
