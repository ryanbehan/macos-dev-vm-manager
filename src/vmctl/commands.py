"""Command implementations and transactional VM state changes."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TextIO

from .catalog import Catalog, Snapshot
from .config import Config
from .doctor import run_checks
from .errors import ArtifactError, StateConflictError, TransactionError, UsageError, VMCTLError
from .helptext import (
    COMMAND_HELP,
    WORKFLOW_HELP,
    render_command_help,
    render_top_help,
    render_workflow_help,
    render_workflows_index,
)
from .initialization import import_bundle, install_bundle, render_init_help
from .lifecycle import LifecycleManager
from .migration import (
    apply_migration_plan,
    create_migration_plan,
    render_migration_plan,
    write_inventory_manifest,
)
from .store import (
    DeletionCategory,
    FileLock,
    atomic_write_json,
    bundle_state,
    clone_bundle,
    move_path,
    path_timestamp,
    permanent_delete_tree,
    timestamp,
    validate_bundle,
    validate_snapshot_name,
)
from .transactions import (
    begin_transaction,
    read_transaction,
    reconcile_transaction,
    set_transaction_phase,
)
from .uninstall import uninstall as uninstall_program


class Commands:
    def __init__(
        self,
        config: Config,
        *,
        catalog: Catalog | None = None,
        lifecycle: LifecycleManager | None = None,
    ) -> None:
        self.config = config
        self.catalog = catalog or Catalog(config)
        self.lifecycle = lifecycle or LifecycleManager(config)

    def handlers(self):
        return {
            "start": self.start,
            "stop": self.stop,
            "shutdown": self.shutdown,
            "status": self.status,
            "snapshot": self.snapshot,
            "list": self.list_snapshots,
            "tree": self.tree,
            "load": self.load,
            "revert": self.load,
            "remove": self.remove,
            "base": self.base,
            "promote": self.promote,
            "commit": self.commit,
            "reset": self.reset,
            "init": self.init,
            "migrate": self.migrate,
            "uninstall": self.uninstall,
            "doctor": self.doctor,
            "help": self.help,
        }

    @staticmethod
    def _require_no_arguments(arguments: list[str], command: str) -> None:
        if arguments:
            raise UsageError(
                f"{command} does not accept arguments: {' '.join(arguments)}",
                hint=f"Run vmctl {command} --help.",
            )

    @staticmethod
    def _single_name(arguments: list[str], command: str) -> str:
        if len(arguments) != 1:
            raise UsageError(
                f"Usage: vmctl {command} NAME",
                hint=f"Run vmctl {command} --help.",
            )
        return validate_snapshot_name(arguments[0])

    def _require_stopped(self) -> None:
        if self.lifecycle.is_running():
            raise StateConflictError(
                "The VM must be stopped for this operation.", hint="Run vmctl stop, then retry."
            )

    def _reconcile_if_needed(self, stdout: TextIO) -> None:
        action = reconcile_transaction(
            self.config,
            self.catalog,
            vm_running=self.lifecycle.is_running(),
        )
        if action == "rolled-back":
            stdout.write("Reconciled interrupted transaction by restoring the previous live VM.\n")
        elif action == "committed-cleanup":
            stdout.write("Completed cleanup for an interrupted committed transaction.\n")

    def start(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        self._require_no_arguments(arguments, "start")
        self.config.ensure_data_directories()
        with FileLock(self.config.lock_file):
            self._reconcile_if_needed(stdout)
            runtime = self.lifecycle.start()
        stdout.write(f"VM runner started (state: {runtime.get('state', 'starting')}).\n")
        return 0

    def stop(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        self._require_no_arguments(arguments, "stop")
        self.lifecycle.stop()
        stdout.write(f"VM suspended and stopped: {self.config.live_bundle}\n")
        return 0

    def shutdown(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        self._require_no_arguments(arguments, "shutdown")
        self.lifecycle.shutdown()
        stdout.write("Guest macOS shut down and the runner exited.\n")
        return 0

    def status(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        self._require_no_arguments(arguments, "status")
        status = self.lifecycle.status()
        live_origin = self.catalog.live_origin()
        try:
            base = self.catalog.get_base()
        except ArtifactError:
            base = "uninitialized"
        runner = "running" if status["running"] else "stopped"
        vm_state = (
            status["runtimeState"] or "running"
            if status["running"]
            else "suspended" if status["savedState"] else "shutdown"
        )
        stdout.write(f"Runner: {runner}\n")
        if status["pid"]:
            stdout.write(f"PID: {status['pid']}\n")
        stdout.write(f"Live VM state: {vm_state}\n")
        stdout.write(f"Live bundle: {self.config.live_bundle}\n")
        stdout.write(f"Loaded from: {live_origin.get('sourceSnapshot') or 'detached'}\n")
        stdout.write(f"Base: {base}\n")
        try:
            journal = read_transaction(self.config)
            transaction = (
                f"{journal.get('operation')} {journal.get('phase')} ({journal.get('id')})"
                if journal is not None
                else "none"
            )
        except Exception as error:
            transaction = f"invalid ({error})"

        def entry_count(path: Path) -> int:
            return sum(1 for _ in path.iterdir()) if path.is_dir() else 0

        pending_count = entry_count(self.config.recovery_dir / "pending")
        failed_count = entry_count(self.config.recovery_dir / "failed")
        legacy_count = sum(
            entry_count(self.config.recovery_dir / name)
            for name in ("live", "removed")
        )
        stdout.write(f"Transaction: {transaction}\n")
        stdout.write(f"Pending rollbacks: {pending_count}\n")
        stdout.write(f"Failed recovery artifacts: {failed_count}\n")
        stdout.write(f"Legacy recovery entries: {legacy_count}\n")
        if status["staleRuntime"]:
            stdout.write("Runtime metadata: stale\n")
        return 0

    def _snapshot_transaction(self, name: str, stdout: TextIO) -> Snapshot:
        validate_snapshot_name(name)
        self._require_stopped()
        validate_bundle(self.config.live_bundle)
        final_directory = self.catalog.snapshot_directory(name)
        if final_directory.exists():
            raise StateConflictError(f"Snapshot already exists: {name}")
        self.config.snapshot_dir.mkdir(parents=True, exist_ok=True)
        temporary_directory = self.config.snapshot_dir / f".tmp-{name}-{uuid.uuid4().hex}"
        try:
            clone_bundle(self.config.live_bundle, temporary_directory / "VM.bundle")
            origin = self.catalog.live_origin()
            parent = (
                origin.get("sourceSnapshot")
                if not origin.get("detached") and isinstance(origin.get("sourceSnapshot"), str)
                else None
            )
            self.catalog.write_snapshot_metadata(
                temporary_directory,
                name=name,
                parent=parent,
                captured_state=bundle_state(temporary_directory / "VM.bundle"),
            )
            os.replace(temporary_directory, final_directory)
        except Exception as error:
            if temporary_directory.exists():
                try:
                    permanent_delete_tree(
                        temporary_directory,
                        expected_root=self.config.snapshot_dir,
                        category=DeletionCategory.SNAPSHOT,
                        live_bundle=self.config.live_bundle,
                    )
                except Exception as cleanup_error:
                    if temporary_directory.exists():
                        failed = self.config.recovery_dir / "failed" / (
                            f"{path_timestamp()}--snapshot-{name}"
                        )
                        move_path(temporary_directory, failed)
                        stdout.write(f"Partial snapshot preserved at: {failed}\n")
                    else:
                        stdout.write(
                            f"Partial snapshot cleanup failed after removing data: {cleanup_error}\n"
                        )
            if isinstance(error, VMCTLError):
                raise
            raise TransactionError(f"Failed to create snapshot {name}: {error}") from error
        stdout.write(f"Snapshot created: {name}\nPath: {final_directory}\n")
        return self.catalog.get(name)

    def snapshot(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        name = self._single_name(arguments, "snapshot")
        self.config.ensure_data_directories()
        with FileLock(self.config.lock_file):
            self._reconcile_if_needed(stdout)
            self._snapshot_transaction(name, stdout)
        return 0

    @staticmethod
    def _format_snapshot(snapshot: Snapshot, live_source: str | None, base: str | None) -> str:
        flags: list[str] = []
        if snapshot.name == base:
            flags.append("base")
        if snapshot.name == live_source:
            flags.append("live-source")
        suffix = f" [{' '.join(flags)}]" if flags else ""
        parent = snapshot.parent or "-"
        return f"{snapshot.name}\t{snapshot.captured_state}\tparent={parent}\t{snapshot.created_at}{suffix}"

    def list_snapshots(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        self._require_no_arguments(arguments, "list")
        active = self.catalog.active_snapshots()
        origin = self.catalog.live_origin().get("sourceSnapshot")
        try:
            base = self.catalog.get_base()
        except ArtifactError:
            base = None
        for snapshot in active:
            stdout.write(self._format_snapshot(snapshot, origin, base) + "\n")
        if not active:
            stdout.write("No snapshots found.\n")
        return 0

    def tree(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        self._require_no_arguments(arguments, "tree")
        lines = self.catalog.tree_lines()
        stdout.write("\n".join(lines) + ("\n" if lines else "No snapshots found.\n"))
        return 0

    def _load_transaction(self, name: str, stdout: TextIO) -> None:
        self._require_stopped()
        source = self.catalog.snapshot_bundle(name)
        validate_bundle(source)
        validate_bundle(self.config.live_bundle)
        identifier = uuid.uuid4().hex
        temporary_live = self.config.live_bundle.parent / (
            f".{self.config.live_bundle.name}.vmctl-{identifier}"
        )
        transaction_directory = (
            self.config.recovery_dir / "pending" / identifier
        )
        rollback = transaction_directory / "VM.bundle"
        previous_origin = self.catalog.live_origin()
        try:
            clone_bundle(source, temporary_live)
            begin_transaction(
                self.config,
                identifier=identifier,
                operation="load",
                source_snapshot=name,
                temporary_live=temporary_live,
                rollback_bundle=rollback,
                previous_live_origin=previous_origin,
            )
            move_path(self.config.live_bundle, rollback)
            set_transaction_phase(self.config, "displaced")
            stdout.write(f"Temporary rollback: {rollback}\n")
            os.replace(temporary_live, self.config.live_bundle)
            set_transaction_phase(self.config, "activated")
            self.catalog.set_live_origin(name)
            validate_bundle(self.config.live_bundle)
            origin = self.catalog.live_origin()
            if origin.get("sourceSnapshot") != name or origin.get("detached"):
                raise TransactionError("Live-origin metadata did not commit correctly")
            set_transaction_phase(self.config, "committed")
            reconcile_transaction(self.config, self.catalog)
        except Exception as error:
            if read_transaction(self.config) is not None:
                try:
                    action = reconcile_transaction(self.config, self.catalog)
                    if action == "rolled-back":
                        stdout.write("Previous live VM restored after load failure.\n")
                except TransactionError as reconciliation_error:
                    raise reconciliation_error from error
            elif temporary_live.exists() or temporary_live.is_symlink():
                try:
                    permanent_delete_tree(
                        temporary_live,
                        expected_root=self.config.live_bundle.parent,
                        category=DeletionCategory.TRANSACTION_TEMPORARY,
                        live_bundle=self.config.live_bundle,
                    )
                except Exception as cleanup_error:
                    failed = self.config.recovery_dir / "failed" / (
                        f"{path_timestamp()}--load-{name}"
                    )
                    move_path(temporary_live, failed)
                    stdout.write(f"Failed live clone preserved at: {failed}\n")
                    raise TransactionError(
                        f"Failed to load snapshot {name}; cleanup also failed: {cleanup_error}"
                    ) from error
            raise TransactionError(f"Failed to load snapshot {name}: {error}") from error
        stdout.write(f"Loaded snapshot: {name}\nLive bundle: {self.config.live_bundle}\n")

    def load(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        name = self._single_name(arguments, "load")
        self.config.ensure_data_directories()
        with FileLock(self.config.lock_file):
            self._reconcile_if_needed(stdout)
            self._load_transaction(name, stdout)
        return 0

    def remove(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        detach = "--detach-live" in arguments
        names = [argument for argument in arguments if argument != "--detach-live"]
        name = self._single_name(names, "remove")
        self.config.ensure_data_directories()
        with FileLock(self.config.lock_file):
            self._reconcile_if_needed(stdout)
            self.catalog.get(name)
            base = self.catalog.get_base()
            if base == name:
                raise StateConflictError(
                    f"Cannot remove the base snapshot: {name}",
                    hint="Promote another snapshot first.",
                )
            origin = self.catalog.live_origin()
            previous_origin: dict | None = None
            if origin.get("sourceSnapshot") == name and not origin.get("detached"):
                if not detach:
                    raise StateConflictError(
                        f"Snapshot {name} is the current live source.",
                        hint="Load another snapshot or retry with --detach-live while stopped.",
                    )
                self._require_stopped()
                previous_origin = origin
                self.catalog.set_live_origin(None, detached=True)
            source = self.catalog.snapshot_directory(name)
            stdout.write(
                f"Permanently deleting snapshot: {name}\nPath: {source}\n"
            )
            try:
                permanent_delete_tree(
                    source,
                    expected_root=self.config.snapshot_dir,
                    category=DeletionCategory.SNAPSHOT,
                    live_bundle=self.config.live_bundle,
                    protected_paths=(self.catalog.snapshot_directory(base),),
                )
            except Exception:
                if previous_origin is not None:
                    atomic_write_json(self.config.live_file, previous_origin)
                raise
        stdout.write(f"Snapshot permanently deleted: {name}\nPath: {source}\n")
        return 0

    def base(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        self._require_no_arguments(arguments, "base")
        stdout.write(self.catalog.get_base() + "\n")
        return 0

    def promote(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        name = self._single_name(arguments, "promote")
        self.config.ensure_data_directories()
        with FileLock(self.config.lock_file):
            self._reconcile_if_needed(stdout)
            self.catalog.set_base(name)
        stdout.write(f"Base snapshot: {name}\n")
        return 0

    def commit(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        name = self._single_name(arguments, "commit")
        self.config.ensure_data_directories()
        with FileLock(self.config.lock_file):
            self._reconcile_if_needed(stdout)
            old_base = self.catalog.get_base()
            snapshot = self._snapshot_transaction(name, stdout)
            try:
                self.catalog.set_base(snapshot.name)
            except Exception as error:
                source = self.catalog.snapshot_directory(name)
                if self.catalog.get_base() != old_base:
                    atomic_write_json(
                        self.config.base_file,
                        {
                            "schemaVersion": 1,
                            "snapshot": old_base,
                            "updatedAt": timestamp(),
                        },
                    )
                try:
                    permanent_delete_tree(
                        source,
                        expected_root=self.config.snapshot_dir,
                        category=DeletionCategory.SNAPSHOT,
                        live_bundle=self.config.live_bundle,
                        protected_paths=(
                            self.catalog.snapshot_directory(old_base),
                        ),
                    )
                except Exception as cleanup_error:
                    if source.exists():
                        failed = self.config.recovery_dir / "failed" / (
                            f"{path_timestamp()}--failed-commit-{name}"
                        )
                        move_path(source, failed)
                        stdout.write(f"Failed commit snapshot preserved at: {failed}\n")
                    raise TransactionError(
                        f"Snapshot {name} could not be promoted and cleanup failed: {cleanup_error}"
                    ) from error
                if isinstance(error, VMCTLError):
                    raise
                raise TransactionError(
                    f"Snapshot {name} was created but could not be promoted: {error}"
                ) from error
        stdout.write(f"Committed and promoted base: {name}\n")
        return 0

    def reset(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        self._require_no_arguments(arguments, "reset")
        self.config.ensure_data_directories()
        with FileLock(self.config.lock_file):
            self._reconcile_if_needed(stdout)
            self._load_transaction(self.catalog.get_base(), stdout)
        return 0

    def init(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        if not arguments:
            render_init_help(stdout)
            return 0
        operation, operation_arguments = arguments[0], arguments[1:]
        if operation == "import":
            import_bundle(self.config, operation_arguments, stdout=stdout)
        elif operation == "install":
            install_bundle(self.config, operation_arguments, stdout=stdout)
        else:
            raise UsageError(
                f"Unknown init operation: {operation}",
                hint="Run vmctl init --help.",
            )
        return 0

    @staticmethod
    def _required_option(arguments: list[str], name: str) -> str:
        if name not in arguments:
            raise UsageError(f"Missing required option: {name}")
        index = arguments.index(name)
        if index + 1 >= len(arguments):
            raise UsageError(f"Missing value for {name}")
        return arguments[index + 1]

    def migrate(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        if not arguments:
            raise UsageError(
                "Usage: vmctl migrate plan --output MANIFEST | "
                "vmctl migrate apply --manifest MANIFEST --approve-digest DIGEST"
            )
        operation = arguments[0]
        if operation == "plan":
            output = Path(
                self._required_option(arguments, "--output")
            ).expanduser().resolve()
            legacy_root = None
            if "--legacy-root" in arguments:
                legacy_root = Path(
                    self._required_option(arguments, "--legacy-root")
                ).expanduser().resolve()
            plan = create_migration_plan(self.config, legacy_root=legacy_root)
            write_inventory_manifest(output, plan)
            stdout.write(render_migration_plan(plan, output))
            return 0
        if operation == "apply":
            manifest = Path(
                self._required_option(arguments, "--manifest")
            ).expanduser().resolve()
            digest = self._required_option(arguments, "--approve-digest")
            self.config.ensure_data_directories()
            with FileLock(self.config.lock_file):
                result = apply_migration_plan(
                    self.config,
                    manifest,
                    approved_digest=digest,
                    vm_running=self.lifecycle.is_running(),
                )
            stdout.write(
                "Migration applied without moving or deleting VM data.\n"
                f"Configuration: {result['configuration']}\n"
            )
            return 0
        raise UsageError(
            f"Unknown migrate operation: {operation}",
            hint="Run vmctl migrate --help.",
        )

    def uninstall(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        stdout.write(
            uninstall_program(
                self.config,
                arguments,
                vm_running=self.lifecycle.is_running(),
            )
        )
        return 0

    def doctor(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        share = arguments == ["--share"]
        if arguments and not share:
            raise UsageError("Usage: vmctl doctor [--share]")
        checks = run_checks(self.config)
        if share:
            from .redaction import redact_check

            checks = [redact_check(check, self.config) for check in checks]
        for check in checks:
            stdout.write(f"[{check.level}] {check.name}: {check.detail}\n")
        return 7 if any(check.level == "FAIL" for check in checks) else 0

    def help(self, arguments: list[str], stdout: TextIO, stderr: TextIO) -> int:
        if not arguments:
            stdout.write(render_top_help())
            return 0
        if len(arguments) != 1:
            raise UsageError("Usage: vmctl help [COMMAND|WORKFLOW]")
        topic = arguments[0]
        if topic == "workflows":
            stdout.write(render_workflows_index())
            return 0
        if topic in COMMAND_HELP:
            stdout.write(render_command_help(topic, self.config))
            return 0
        if topic in WORKFLOW_HELP:
            stdout.write(render_workflow_help(topic))
            return 0
        raise UsageError(
            f"Unknown help topic: {topic}", hint="Run vmctl help workflows."
        )


def build_handlers(config: Config | None = None):
    configured = config or Config.from_environment()
    return Commands(configured).handlers()
