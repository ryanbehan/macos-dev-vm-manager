"""Command dispatch for the project-local ``vmctl`` executable."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from .config import Config
from .errors import VMCTLError
from .helptext import render_command_help, render_top_help
from . import __version__


APPROVED_COMMANDS = (
    "start",
    "stop",
    "shutdown",
    "status",
    "snapshot",
    "list",
    "tree",
    "load",
    "revert",
    "remove",
    "base",
    "promote",
    "commit",
    "reset",
    "init",
    "migrate",
    "uninstall",
    "doctor",
    "help",
)

CommandHandler = Callable[[list[str], TextIO, TextIO], int]


def main(
    argv: Sequence[str] | None = None,
    *,
    handlers: dict[str, CommandHandler] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Dispatch one command and return a process exit status."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr

    if not arguments or arguments[0] in {"-h", "--help"}:
        output.write(render_top_help())
        return 0
    if arguments == ["--version"]:
        output.write(f"vmctl {__version__} protocol=1\n")
        return 0

    command = arguments[0]
    command_arguments = arguments[1:]

    if command not in APPROVED_COMMANDS:
        error_output.write(
            f"vmctl: Unknown command: {command}\n"
            "Run 'vmctl help' to see available commands.\n"
        )
        return 2

    config = Config.from_environment()
    if command_arguments == ["--help"]:
        output.write(render_command_help(command, config))
        return 0

    if handlers is None:
        from .commands import build_handlers

        registered_handlers = build_handlers(config)
    else:
        registered_handlers = handlers
    handler = registered_handlers.get(command)
    if handler is None:
        error_output.write(
            f"vmctl: {command} is not implemented yet.\n"
            "Run 'vmctl help' to see the current command index.\n"
        )
        return 4

    try:
        return handler(command_arguments, output, error_output)
    except VMCTLError as error:
        error_output.write(f"vmctl: {error.message}\n")
        if error.hint:
            error_output.write(f"Next: {error.hint}\n")
        return error.exit_code
