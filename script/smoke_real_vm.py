#!/usr/bin/env python3
"""Guarded destructive smoke test limited to snapshots created by this run."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vmctl.catalog import Catalog  # noqa: E402
from vmctl.config import Config  # noqa: E402
from vmctl.lifecycle import LifecycleManager  # noqa: E402
from vmctl.store import atomic_write_json, clone_bundle, read_json, validate_bundle  # noqa: E402
from vmctl.transactions import begin_transaction  # noqa: E402


class SmokeFailure(RuntimeError):
    pass


def run_vmctl(*arguments: str, timeout: int = 420) -> str:
    command = [str(PROJECT_ROOT / "vmctl"), *arguments]
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode != 0:
        raise SmokeFailure(
            f"vmctl {' '.join(arguments)} failed with exit {result.returncode}"
        )
    return result.stdout


def exercise_shutdown() -> str:
    command = [str(PROJECT_ROOT / "vmctl"), "shutdown"]
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=420,
    )
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode == 0:
        return "guest-exited"
    if (
        result.returncode == 5
        and "guest accepted shutdown but has not exited" in result.stderr.lower()
    ):
        print(
            "Locked guest accepted shutdown but did not exit; validating bounded failure and suspending safely.",
            flush=True,
        )
        run_vmctl("stop")
        return "accepted-timeout-safe-stop"
    raise SmokeFailure(f"vmctl shutdown failed with exit {result.returncode}")


def snapshot_exists(catalog: Catalog, name: str) -> bool:
    return catalog.snapshot_directory(name).is_dir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the guarded real-VM smoke sequence and restore original state."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required acknowledgment that this starts the VM and deletes only snapshots created by this run",
    )
    arguments = parser.parse_args(argv)
    if not arguments.execute:
        parser.error("--execute is required")

    config = Config.from_environment()
    catalog = Catalog(config)
    lifecycle = LifecycleManager(config)
    if lifecycle.is_running():
        raise SmokeFailure("VM runner must be stopped before the smoke test")
    if config.transaction_file.exists():
        raise SmokeFailure(f"Unfinished transaction exists: {config.transaction_file}")
    pending = config.recovery_dir / "pending"
    if pending.is_dir() and any(pending.iterdir()):
        raise SmokeFailure(f"Pending recovery data exists: {pending}")
    validate_bundle(config.live_bundle)

    original_base = catalog.get_base()
    catalog.get(original_base)
    original_live_metadata = (
        read_json(config.live_file) if config.live_file.exists() else None
    )
    original_free = shutil.disk_usage(config.live_bundle.parent).free
    if original_free < 20 * 1024**3:
        raise SmokeFailure("At least 20 GiB free space is required for the smoke test")

    suffix = uuid.uuid4().hex[:10]
    names = {
        "guard": f"vmctl-smoke-{suffix}-guard",
        "ancestor": f"vmctl-smoke-{suffix}-ancestor",
        "branch": f"vmctl-smoke-{suffix}-branch",
        "commit": f"vmctl-smoke-{suffix}-commit",
        "reconciled": f"vmctl-smoke-{suffix}-reconciled",
    }
    for name in names.values():
        if snapshot_exists(catalog, name):
            raise SmokeFailure(f"Unique smoke snapshot unexpectedly exists: {name}")

    created: set[str] = set()
    report = {
        "originalBase": original_base,
        "originalLive": original_live_metadata,
        "originalFreeBytes": original_free,
        "names": names,
    }
    primary_error: Exception | None = None
    try:
        run_vmctl("snapshot", names["guard"])
        created.add(names["guard"])

        run_vmctl("start")
        run_vmctl("stop")
        run_vmctl("start")
        report["shutdownResult"] = exercise_shutdown()

        run_vmctl("snapshot", names["ancestor"])
        created.add(names["ancestor"])
        run_vmctl("load", names["ancestor"])
        run_vmctl("snapshot", names["branch"])
        created.add(names["branch"])
        run_vmctl("load", names["branch"])
        run_vmctl("remove", names["ancestor"])
        created.remove(names["ancestor"])
        tree = run_vmctl("tree")
        if f"{names['ancestor']} [deleted]" not in tree:
            raise SmokeFailure("Tree did not render the deleted smoke ancestor")

        run_vmctl("promote", names["branch"])
        run_vmctl("reset")
        run_vmctl("commit", names["commit"])
        created.add(names["commit"])

        identifier = f"smoke{suffix}"
        temporary_live = config.live_bundle.parent / (
            f".{config.live_bundle.name}.vmctl-{identifier}"
        )
        rollback = config.recovery_dir / "pending" / identifier / "VM.bundle"
        clone_bundle(catalog.snapshot_bundle(names["guard"]), temporary_live)
        begin_transaction(
            config,
            identifier=identifier,
            operation="load",
            source_snapshot=names["guard"],
            temporary_live=temporary_live,
            rollback_bundle=rollback,
            previous_live_origin=catalog.live_origin(),
        )
        output = run_vmctl("snapshot", names["reconciled"])
        if "Reconciled interrupted transaction" not in output:
            raise SmokeFailure("Prepared transaction was not reconciled")
        created.add(names["reconciled"])
    except Exception as error:
        primary_error = error
        print(f"Smoke test failed: {error}", file=sys.stderr, flush=True)
    finally:
        cleanup_errors: list[str] = []
        try:
            if lifecycle.is_running():
                run_vmctl("stop")
        except Exception as error:
            cleanup_errors.append(f"stop: {error}")

        if snapshot_exists(catalog, names["guard"]):
            try:
                run_vmctl("load", names["guard"])
                if original_live_metadata is None:
                    config.live_file.unlink(missing_ok=True)
                else:
                    atomic_write_json(config.live_file, original_live_metadata)
            except Exception as error:
                cleanup_errors.append(f"restore live guard: {error}")

        try:
            if catalog.get_base() != original_base:
                run_vmctl("promote", original_base)
        except Exception as error:
            cleanup_errors.append(f"restore base: {error}")

        for name in sorted(created, reverse=True):
            if not snapshot_exists(catalog, name):
                continue
            try:
                run_vmctl("remove", name)
            except Exception as error:
                cleanup_errors.append(f"remove {name}: {error}")

        report["finalFreeBytes"] = shutil.disk_usage(config.live_bundle.parent).free
        report["finalBase"] = catalog.get_base()
        report["finalLive"] = catalog.live_origin()
        report["transactionExists"] = config.transaction_file.exists()
        report["pendingEntries"] = (
            sum(1 for _ in pending.iterdir()) if pending.is_dir() else 0
        )
        report["remainingSmokeSnapshots"] = [
            name for name in names.values() if snapshot_exists(catalog, name)
        ]
        print(json.dumps(report, indent=2, sort_keys=True), flush=True)

        if cleanup_errors:
            raise SmokeFailure("; ".join(cleanup_errors))
        if report["finalBase"] != original_base:
            raise SmokeFailure("Original base was not restored")
        if report["finalLive"] != original_live_metadata:
            raise SmokeFailure("Original live-origin metadata was not restored")
        if report["transactionExists"] or report["pendingEntries"]:
            raise SmokeFailure("Transaction residue remains after smoke test")
        if report["remainingSmokeSnapshots"]:
            raise SmokeFailure("Smoke snapshots remain after cleanup")
        if primary_error is not None:
            raise primary_error
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SmokeFailure, subprocess.TimeoutExpired) as error:
        print(f"vmctl smoke: {error}", file=sys.stderr)
        raise SystemExit(1)
