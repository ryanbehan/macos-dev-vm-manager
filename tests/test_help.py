from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from helpers import make_config  # noqa: E402
from vmctl.cli import APPROVED_COMMANDS, main  # noqa: E402
from vmctl.commands import Commands  # noqa: E402
from vmctl.helptext import (  # noqa: E402
    COMMAND_HELP,
    WORKFLOW_HELP,
    render_command_help,
    render_top_help,
)


class HelpCoverageTests(unittest.TestCase):
    def test_every_approved_command_has_complete_help(self) -> None:
        self.assertEqual(set(APPROVED_COMMANDS), set(COMMAND_HELP))
        for name, entry in COMMAND_HELP.items():
            with self.subTest(command=name):
                self.assertTrue(entry.syntax)
                self.assertTrue(entry.prerequisites)
                self.assertTrue(entry.changes)
                self.assertTrue(entry.safety)
                self.assertTrue(entry.example)
                self.assertIn(entry.workflow, WORKFLOW_HELP)

    def test_command_and_workflow_help_are_dispatchable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            handlers = Commands(config).handlers()
            for topic in [*APPROVED_COMMANDS, *WORKFLOW_HELP, "workflows"]:
                stdout = io.StringIO()
                stderr = io.StringIO()
                result = main(["help", topic], handlers=handlers, stdout=stdout, stderr=stderr)
                self.assertEqual(result, 0, topic)
                self.assertTrue(stdout.getvalue(), topic)
                self.assertEqual(stderr.getvalue(), "", topic)

    def test_command_local_help_is_available_for_every_command(self) -> None:
        for command in APPROVED_COMMANDS:
            with self.subTest(command=command):
                stdout = io.StringIO()
                stderr = io.StringIO()
                result = main(
                    [command, "--help"],
                    stdout=stdout,
                    stderr=stderr,
                )
                self.assertEqual(result, 0)
                self.assertIn("Prerequisites:", stdout.getvalue())
                self.assertIn("Safety and exit behavior:", stdout.getvalue())
                self.assertEqual(stderr.getvalue(), "")

    def test_help_describes_permanent_removal_and_bounded_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            remove_help = render_command_help("remove", config).lower()
            self.assertIn("permanent", remove_help)
            self.assertIn("base", remove_help)
            self.assertIn("detach", remove_help)
            self.assertIn("independently loadable", remove_help)

        self.assertNotIn("undelete", COMMAND_HELP)
        self.assertNotIn("undelete", render_top_help())
        self.assertIn("snapshot", WORKFLOW_HELP["recovery"].lower())
        self.assertIn("transaction", WORKFLOW_HELP["recovery"].lower())
        self.assertIn("recovery/failed", WORKFLOW_HELP["recovery"])
        self.assertIn("before loading", WORKFLOW_HELP["snapshots"].lower())


if __name__ == "__main__":
    unittest.main()
