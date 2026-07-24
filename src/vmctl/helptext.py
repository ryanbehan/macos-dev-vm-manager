"""Single-source command and workflow help."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config


@dataclass(frozen=True)
class HelpEntry:
    syntax: str
    summary: str
    prerequisites: str
    changes: str
    safety: str
    example: str
    workflow: str


COMMAND_HELP: dict[str, HelpEntry] = {
    "start": HelpEntry("vmctl start", "Start or resume the live VM.", "A valid live bundle and strictly verified signed runner.", "Verifies signature and exact entitlements, launches VMRunner.app, and may consume a saved state file while restoring.", "Rejects duplicate launches, quarantine, invalid signatures, and unapproved entitlements. It never changes Gatekeeper trust metadata.", "vmctl start", "lifecycle"),
    "stop": HelpEntry("vmctl stop", "Suspend the VM and close its window.", "The VM runner must be running.", "Creates SaveFile.vzvmsave and exits the runner.", "Uses graceful AppKit termination and never force-kills on timeout.", "vmctl stop", "lifecycle"),
    "shutdown": HelpEntry("vmctl shutdown", "Ask guest macOS to shut down.", "The VM runner must be running and accept requestStop().", "Shuts down guest macOS and exits without a suspended state. Guest macOS may show its normal shutdown confirmation; choose Shut Down or press Return in the VM window.", "Reports rejection or timeout without force-stopping the VM. A timeout leaves the VM open for safe confirmation.", "vmctl shutdown", "lifecycle"),
    "status": HelpEntry("vmctl status", "Show runner, saved-state, live-source, and base state.", "None.", "Read-only.", "Stale runtime metadata is identified rather than trusted.", "vmctl status", "lifecycle"),
    "snapshot": HelpEntry("vmctl snapshot NAME", "Create an immutable named snapshot.", "The VM runner must be stopped and the live bundle valid.", "Creates an APFS copy-on-write clone and metadata.", "Never overwrites an existing snapshot or modifies the live VM.", "vmctl snapshot dev-ready", "snapshots"),
    "list": HelpEntry("vmctl list", "List named snapshots.", "Catalog metadata must be readable.", "Read-only.", "Validates metadata while listing.", "vmctl list", "snapshots"),
    "tree": HelpEntry("vmctl tree", "Show logical snapshot ancestry.", "Catalog metadata must be readable.", "Read-only.", "Parentage is informational; children never depend on parent files.", "vmctl tree", "branching"),
    "load": HelpEntry("vmctl load NAME", "Load a fresh working copy of a snapshot.", "The VM runner must be stopped, the live bundle valid, and the snapshot valid.", "Temporarily moves the current live bundle under recovery/pending, activates a fresh clone, commits live-origin metadata, then permanently deletes the rollback.", "Stored snapshots are never booted or modified. Snapshot the current live VM before loading if you want to keep it.", "vmctl load initial", "snapshots"),
    "revert": HelpEntry("vmctl revert NAME", "Alias for vmctl load.", "Same as load.", "Uses the same transaction-scoped rollback and post-commit cleanup as load.", "Does not retain the previous live VM after a successful commit.", "vmctl revert dev-ready", "snapshots"),
    "remove": HelpEntry("vmctl remove NAME [--detach-live]", "Permanently delete a snapshot.", "The snapshot cannot be the base; a current live source needs explicit --detach-live while the VM is stopped.", "Permanently deletes the exact selected snapshot bundle and metadata path.", "Deletion is permanent. Base, live, symlink, escaped, and attached live-source paths are rejected. Children remain independently loadable and show a synthetic [deleted] parent.", "vmctl remove obsolete-test  # PERMANENT", "recovery"),
    "base": HelpEntry("vmctl base", "Show the immutable reset baseline.", "Base metadata must exist.", "Read-only.", "The base is separate from the disposable live VM.bundle.", "vmctl base", "base"),
    "promote": HelpEntry("vmctl promote NAME", "Designate an existing snapshot as the base.", "The named snapshot must be valid.", "Atomically changes the base pointer only.", "Preserves the previous base as an ordinary snapshot.", "vmctl promote dev-ready", "base"),
    "commit": HelpEntry("vmctl commit NAME", "Snapshot the live VM and promote it as base.", "The VM must be stopped and NAME unused.", "Creates and validates a snapshot, then atomically changes the base pointer.", "If promotion fails, the old base remains and the just-created snapshot is permanently deleted; only an uncleanable failure is retained under recovery/failed.", "vmctl commit new-base", "base"),
    "reset": HelpEntry("vmctl reset", "Load a fresh working copy of the current base.", "The VM runner must be stopped, and both live and base bundles must be valid.", "Uses transaction-scoped rollback while cloning the base, then deletes rollback data after commit.", "Never modifies the base snapshot. Snapshot current live state first if it must be retained.", "vmctl reset", "base"),
    "init": HelpEntry("vmctl init [import|install] ...", "Initialize from an existing bundle or an Apple restore image.", "A source installation; use clone import by default, or a compatible Apple IPSW/latest restore image. Shut down an existing VM before import.", "Prints a complete plan first and writes only after --yes. Clone import leaves its source unchanged. A suspended source requires explicit --discard-saved-state in clone mode because saved state may not restore across runner builds. Fresh install downloads directly from the Apple URL returned by Virtualization.framework.", "Never bundles, mirrors, uploads, or publishes macOS media or VM data. Adopt mode changes permissions only after approval and cannot discard saved state.", "vmctl init import /path/to/VM.bundle --mode clone --yes", "setup"),
    "migrate": HelpEntry("vmctl migrate plan ... | vmctl migrate apply ...", "Adopt an existing installation's data paths without moving data.", "A valid stopped existing VM and catalog.", "Plan is read-only and digest-bound; apply writes only portable configuration.", "Migration never moves or deletes VM, snapshot, recovery, or state data.", "vmctl migrate plan --output /tmp/vmctl-migration.json", "migration"),
    "uninstall": HelpEntry("vmctl uninstall [--purge-data --approve-path PATH]", "Remove installed program files while preserving VM data by default.", "A valid install manifest. Data purge additionally requires a stopped VM and exact canonical data path.", "Default removes only manifest-owned launcher/current/releases. Purge permanently removes the portable data root.", "Default uninstall preserves config, live VM, snapshots, recovery, state, and logs. Purge is permanent and separately approved.", "vmctl uninstall", "migration"),
    "doctor": HelpEntry("vmctl doctor [--share]", "Run non-mutating readiness diagnostics.", "None.", "Read-only checks of architecture, paths, VM, catalog, transaction state, exceptional recovery, signature, exact entitlements, storage, and PATH. --share redacts local identifiers.", "Does not launch, change, or delete VM data.", "vmctl doctor --share", "diagnostics"),
    "help": HelpEntry("vmctl help [COMMAND|WORKFLOW]", "Show task-oriented help.", "None.", "Read-only.", "Examples avoid overwrites and force-kills; permanent deletion examples are explicitly labeled.", "vmctl help workflows", "lifecycle"),
}


WORKFLOW_HELP: dict[str, str] = {
    "setup": "Install from source with `./script/install-from-source.sh`; Python 3.10+, Apple silicon, macOS 26+, and Command Line Tools containing Swift 6 are required. Full Xcode and a signing certificate are not required. Run `xcode-select --install` if tools are missing. Shut down an existing source VM, then use `vmctl init import PATH --mode clone --yes`; if only suspended state is available, review clone import with `--discard-saved-state`. Or review `vmctl init install --restore latest` and rerun with `--yes`. Apple restore media remains local and is removed from cache by default.",
    "lifecycle": "Start with `vmctl start`. Use `vmctl stop` to suspend and resume later; use `vmctl shutdown` for a clean guest macOS shutdown. If macOS shows a shutdown confirmation in the VM window, choose Shut Down or press Return. Check `vmctl status` at any time.",
    "snapshots": "Stop the VM and run `vmctl snapshot NAME` before loading another state whenever the current live VM must be retained. Inspect immutable, independently loadable snapshots with `vmctl list` or `vmctl tree`, then use `vmctl load NAME`; the stored snapshot is never booted or modified.",
    "branching": "Load an older snapshot, start and change the VM, stop it, then create a new snapshot. Its parent is logical metadata only. Every child is independently loadable; if a parent is permanently removed, the tree shows a synthetic [deleted] parent without retaining its files.",
    "base": "The base is an immutable named snapshot; $HOME/VM.bundle is the disposable live working copy. Use `vmctl promote NAME` for an existing snapshot, `vmctl commit NAME` to snapshot live and atomically promote it, and `vmctl reset` to clone the base into live through bounded rollback.",
    "recovery": "Load, revert, and reset use a journaled transaction under recovery/pending. The previous live bundle exists only until commit and is then permanently deleted. An interrupted pre-commit transaction is rolled back on the next mutating command; only rollback or cleanup failures persist under recovery/failed. Snapshot live state before loading if you need to retain it. Legacy recovery/live and recovery/removed data is handled only by the separately reviewed migration utility.",
    "migration": "Use `vmctl migrate plan --output MANIFEST` to review exact existing paths, or add `--legacy-root /path/to/old/checkout` for the original project-local layout. Apply only with the displayed digest; no VM data moves or is deleted. Legacy recovery/live and recovery/removed inventory remains available through the retained source checkout's `script/migrate_legacy_recovery.py`; execution is digest-bound permanent cleanup. `vmctl uninstall` removes program files but preserves VM data. `--purge-data --approve-path EXACT_PATH` is a separate permanent operation.",
    "diagnostics": "`vmctl doctor` shows local diagnostic detail. Use `vmctl doctor --share` for issue reports; it strips terminal controls and redacts home paths, usernames, VM paths, snapshot names, and signer identity. vmctl has no telemetry and does not upload diagnostics.",
    "limitations": "The first release supports one Apple-silicon macOS VM at a time on macOS 26+. Earlier macOS hosts remain unsupported until their real-VM smoke gates pass. Clipboard sharing and host/guest drag-and-drop are not implemented by this runner; use guest networking, SSH, or a separately configured file-sharing method. APFS clones share blocks, so directory-size tools can overstate physically reclaimable storage.",
}


def render_top_help() -> str:
    lines = [
        "Usage: vmctl <command> [arguments]",
        "",
        "Manage the local macOS development VM from any directory.",
        "",
        "Quick start:",
        "  vmctl status",
        "  vmctl start",
        "  vmctl stop                 # suspend and close",
        "  vmctl snapshot dev-ready",
        "  vmctl load dev-ready",
        "  vmctl help workflows",
        "",
        "Commands:",
    ]
    width = max(len(name) for name in COMMAND_HELP)
    for name, entry in COMMAND_HELP.items():
        lines.append(f"  {name:<{width}}  {entry.summary}")
    lines.extend(
        [
            "",
            "Workflows: setup, lifecycle, snapshots, branching, base, recovery, migration, diagnostics, limitations",
            "Run `vmctl help COMMAND` or `vmctl help WORKFLOW` for details.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_command_help(name: str, config: Config) -> str:
    entry = COMMAND_HELP[name]
    return (
        f"Usage: {entry.syntax}\n\n"
        f"Purpose:\n  {entry.summary}\n\n"
        f"Prerequisites:\n  {entry.prerequisites}\n\n"
        f"State changes and affected paths:\n  {entry.changes}\n"
        f"  Live: {config.live_bundle}\n"
        f"  Snapshots: {config.snapshot_dir}\n"
        f"  Recovery: {config.recovery_dir}\n\n"
        f"  State: {config.state_dir}\n"
        f"  Application: {config.app_bundle}\n"
        f"  Launcher: {config.launcher_path}\n\n"
        f"Safety and exit behavior:\n  {entry.safety}\n"
        "  Returns nonzero when validation, state, lifecycle, or transaction checks fail.\n\n"
        f"Example:\n  {entry.example}\n\n"
        f"Related workflow:\n  vmctl help {entry.workflow}\n"
    )


def render_workflow_help(name: str) -> str:
    return f"Workflow: {name}\n\n{WORKFLOW_HELP[name]}\n"


def render_workflows_index() -> str:
    lines = ["Workflow help:"]
    for name in WORKFLOW_HELP:
        lines.append(f"  vmctl help {name}")
    return "\n".join(lines) + "\n"
