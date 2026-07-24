#!/usr/bin/env python3
"""Inventory or explicitly execute the reviewed legacy-recovery migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vmctl.config import Config  # noqa: E402
from vmctl.errors import VMCTLError  # noqa: E402
from vmctl.lifecycle import LifecycleManager  # noqa: E402
from vmctl.migration import (  # noqa: E402
    execute_legacy_recovery,
    inventory_legacy_recovery,
    write_inventory_manifest,
)
from vmctl.store import FileLock  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory legacy vmctl recovery data by default. Execution requires "
            "an unchanged manifest and its explicitly approved digest."
        )
    )
    parser.add_argument("--manifest", type=Path, help="Write or read the review manifest")
    parser.add_argument("--execute", action="store_true", help="Permanently delete reviewed candidates")
    parser.add_argument("--approve-digest", help="Exact candidateDigest from the reviewed manifest")
    arguments = parser.parse_args(argv)
    config = Config.from_environment()

    try:
        if arguments.execute:
            if arguments.manifest is None or not arguments.approve_digest:
                parser.error("--execute requires --manifest and --approve-digest")
            with FileLock(config.lock_file):
                result = execute_legacy_recovery(
                    config,
                    arguments.manifest,
                    approved_digest=arguments.approve_digest,
                    vm_running=LifecycleManager(config).is_running(),
                )
        else:
            result = inventory_legacy_recovery(config)
            if arguments.manifest is not None:
                write_inventory_manifest(arguments.manifest, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except VMCTLError as error:
        print(f"vmctl migration: {error.message}", file=sys.stderr)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
