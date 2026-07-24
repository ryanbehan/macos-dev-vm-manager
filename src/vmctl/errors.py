"""Typed user-facing failures and stable process exit codes."""

from __future__ import annotations


class VMCTLError(Exception):
    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class UsageError(VMCTLError):
    exit_code = 2


class StateConflictError(VMCTLError):
    exit_code = 3


class ArtifactError(VMCTLError):
    exit_code = 4


class LifecycleError(VMCTLError):
    exit_code = 5


class TransactionError(VMCTLError):
    exit_code = 6


class EnvironmentError(VMCTLError):
    exit_code = 7
