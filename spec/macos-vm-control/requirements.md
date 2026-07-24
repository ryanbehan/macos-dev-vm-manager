# Feature: macOS VM Control

## Introduction

Provide a small local command-line interface for operating the existing Apple Virtualization sample VM without opening Xcode. The interface will launch the already signed VM application, stop it safely, create named copy-on-write snapshots, restore a selected snapshot, permanently remove snapshots on request, and report current state without accumulating successful-operation rollback bundles. The live VM remains at `$HOME/VM.bundle`, because Apple’s sample application expects that location.

## Requirements

1. User Story: As a developer, I want to start, suspend, and shut down the macOS VM from Terminal, so that normal VM use does not require Xcode.
   1. The system shall provide a `vmctl start` command that launches a stable, locally stored copy of the signed `macOSVirtualMachineSampleApp.app`.
   2. When the VM application is already running, the system shall report that state without launching a duplicate instance.
   3. The system shall provide a `vmctl stop` command that asks the VM application to terminate normally, saves a resumable suspended state, and waits for its process to exit.
   4. The system shall provide a `vmctl shutdown` command that asks a running guest to shut down through `VZVirtualMachine.canRequestStop` and `VZVirtualMachine.requestStop()` and waits for the VM application to exit.
   5. If the guest cannot accept a shutdown request, the system shall report that state without forcibly stopping the VM.
   6. If normal termination or guest shutdown does not complete within a bounded timeout, the system shall report the failure without force-killing the application or modifying the VM bundle.
   7. The system shall provide a `vmctl status` command that reports whether the VM application is running, stopped with saved state, or stopped without saved state.

2. User Story: As a developer, I want named VM snapshots, so that I can preserve useful test states and return to them later.
   1. The system shall provide a `vmctl snapshot <name>` command that operates only while the VM application is stopped.
   2. The snapshot command shall validate the live VM bundle before copying it.
   3. The snapshot command shall copy the entire live VM bundle, including disk, hardware model, machine identifier, auxiliary storage, and saved state when present.
   4. When the source and destination support APFS cloning, the snapshot command shall use copy-on-write clones to avoid initially duplicating the VM’s physical storage.
   5. If a snapshot with the requested name already exists, the system shall fail without overwriting it.
   6. The system shall provide a `vmctl list` command that lists available named snapshots with creation time, parent snapshot, captured VM state, and an indication of the snapshot from which the live VM was loaded.
   7. The system shall provide a `vmctl tree` command that displays the logical parent/child history of snapshots.
   8. When a snapshot is created from a live VM that was loaded from another snapshot, the system shall record the source snapshot as its logical parent.
   9. Snapshot parentage shall be informational metadata and shall not create a runtime dependency on the parent bundle.
   10. Each snapshot shall remain independently loadable even if its logical parent is later permanently removed.

3. User Story: As a developer, I want to load snapshots safely, so that failed experiments do not destroy either my baseline or the current VM state.
   1. The system shall provide a `vmctl load <name>` command that operates only while the VM application is stopped, with `vmctl revert <name>` available as an alias for users familiar with revert terminology.
   2. Before replacing the live VM, the system shall validate that the selected snapshot contains all required VM artifacts.
   3. Before activating the selected snapshot, the system shall move the current live VM bundle to a transaction-scoped temporary rollback location.
   4. The load command shall create a fresh copy-on-write clone from the selected snapshot and shall never boot or modify the stored snapshot directly.
   5. If restoration fails before commit, the system shall restore the previous live bundle automatically when possible and preserve diagnostic artifacts only when automatic rollback cannot complete safely.
   6. Loading a snapshot shall update live-VM metadata so that a subsequent snapshot becomes a logical child of the loaded snapshot.
   7. Loading an older snapshot and creating a new snapshot shall create a new logical branch without altering existing snapshots.
   8. After the new live bundle and live-origin metadata are validated and committed, the system shall permanently delete the temporary rollback bundle rather than retaining it under `recovery/live`.
   9. The system shall journal the active load or reset transaction so that an interrupted operation can be reconciled safely on the next mutating invocation.

4. User Story: As a developer, I want predictable local paths and clear commands, so that the workflow is easy to remember and inspect.
   1. The system shall provide one project-local executable named `vmctl` with `start`, `stop`, `shutdown`, `status`, `snapshot`, `list`, `tree`, `load`, `revert`, `remove`, `base`, `promote`, `commit`, `reset`, `doctor`, and `help` commands.
   2. The system shall store the stable signed application under the project directory rather than depending on Xcode DerivedData after setup.
   3. The system shall store named snapshots, transaction journals, temporary rollback data, and exceptional failed-transaction artifacts under configured local paths.
   4. The system shall use `$HOME/VM.bundle` as the default live bundle path while allowing explicit path overrides through documented environment variables.
   5. After the initial signed application is staged, normal VM operations shall not launch Xcode or invoke `xcodebuild`.
   6. The system shall provide an installation command that creates or updates `$HOME/.local/bin/vmctl` as a stable launcher for the project-local utility.
   7. The installation command shall preserve the project-local implementation as the source of truth and shall not copy an independently editable duplicate into the shell path.
   8. The installation command shall verify that `vmctl` resolves through the active shell with `command -v vmctl` and shall print the resolved path.
   9. When `$HOME/.local/bin` is already present in the user’s shell path, the installation command shall not modify `.zshrc`, `.zprofile`, or other shell startup files.
   10. After installation, the user shall be able to invoke `vmctl` from any working directory.

5. User Story: As a developer, I want safe failure behavior, so that a typo or interrupted command cannot silently destroy VM data.
   1. The system shall reject empty names, path traversal, absolute paths, and unsupported characters in snapshot names.
   2. The system shall use a lock to prevent overlapping mutating commands.
   3. Before any permanent tree deletion, the system shall verify that the target is an expected snapshot, transaction-temporary, or explicitly selected legacy-recovery path and shall reject symlinks, path escapes, the live VM, and protected snapshots.
   4. The system shall print the affected live, snapshot, transaction, and exceptional recovery paths before or immediately after each state-changing operation.
   5. The system shall return a nonzero status for invalid state, invalid input, missing artifacts, launch failure, stop timeout, snapshot failure, or revert failure.

6. User Story: As a maintainer, I want automated validation of the control workflow, so that safety behavior can be checked without risking the real VM.
   1. The system shall include automated tests that use temporary fake VM bundles and stubbed process/application commands.
   2. The tests shall cover command parsing, name validation, running-state guards, duplicate snapshot protection, snapshot listing, logical tree creation, independent child loading, permanent snapshot removal, safe loading and reverting, rollback cleanup, interruption reconciliation, and exceptional failure recovery.
   3. The system shall provide a non-mutating diagnostic command or mode that verifies the configured application, signing entitlement, live bundle, snapshot directory, and available storage.
   4. The tests shall cover launcher installation, launcher replacement, and shell-path verification without modifying the user’s real shell startup files.

7. User Story: As a developer, I want to remove obsolete snapshots and promote trusted states to the reset baseline, so that snapshot storage and the default VM state remain manageable.
   1. The system shall provide a `vmctl remove <name>` command that permanently deletes the selected snapshot bundle and metadata after all protections succeed.
   2. The remove command shall print that deletion is permanent and print the exact snapshot path being deleted.
   3. The system shall not provide undeletion for snapshots removed under the permanent-deletion model.
   4. When a logical parent has been deleted, `vmctl tree` shall display a synthetic `[deleted]` ancestor derived from surviving child metadata without retaining the deleted bundle.
   5. The system shall reject removal of the designated base snapshot until another snapshot is promoted as the base.
   6. The system shall reject removal of the snapshot from which the current live VM was loaded unless the user first loads another snapshot or explicitly detaches the stopped live VM from that source.
   7. The system shall maintain a single base pointer that identifies the immutable snapshot used for default resets.
   8. The system shall provide a `vmctl base` command that reports the current base snapshot.
   9. The system shall provide a `vmctl promote <name>` command that atomically designates an existing valid snapshot as the new base without modifying or copying that snapshot’s VM bundle.
   10. Promoting a new base shall preserve the previous base as an ordinary named snapshot unless the user removes it separately.
   11. The system shall provide a `vmctl reset` command that safely loads a fresh working copy of the current base snapshot using the same temporary rollback-and-cleanup transaction as `load`.
   12. The system shall provide a `vmctl commit <new-name>` command that creates a snapshot from the stopped live VM and promotes the new snapshot as the base only if both operations succeed.
   13. If snapshot creation or base promotion fails during commit, the system shall leave the prior base pointer unchanged and shall delete an unpromoted snapshot created solely by that failed commit after validating its path.
   14. The initial base pointer shall reference the existing `initial` snapshot.
   15. Automated tests shall cover protected-base deletion, permanent removal, deleted-parent tree rendering, base promotion, reset cleanup, atomic commit success, and commit rollback behavior.
   16. Legacy `recovery/live` and `recovery/removed` data shall be cleaned only through a separately reviewed migration that defaults to inventory-only output and requires explicit execution approval.

8. User Story: As a developer, I want comprehensive and scenario-oriented help, so that I can use every lifecycle, snapshot, base, and recovery operation without consulting source code.
   1. The system shall provide equivalent `vmctl help`, `vmctl --help`, and `vmctl -h` entry points with a concise quick start and complete command index.
   2. The system shall provide `vmctl help <command>` and `vmctl <command> --help` for every command.
   3. Each command help page shall describe syntax, purpose, prerequisites, affected paths, state changes, safety checks, exit behavior, and at least one realistic example.
   4. The top-level help shall distinguish `stop`, which saves suspended state, from `shutdown`, which asks guest macOS to shut down.
   5. The system shall provide scenario help for initial setup, everyday start and stop, clean guest shutdown, creating and listing snapshots, understanding the snapshot tree, loading an older snapshot, creating a branch, promoting an existing snapshot, committing the live VM as the base, resetting to base, permanently removing snapshots, and recovering from an interrupted or failed load or revert.
   6. The system shall expose scenario help through `vmctl help workflows`, with discoverable topics for `lifecycle`, `snapshots`, `branching`, `base`, and `recovery`.
   7. Snapshot help shall explicitly explain that parentage is logical metadata, every snapshot is independently loadable, and stored snapshots are never booted or modified directly.
   8. Base help shall explicitly explain the difference between the immutable base snapshot and the disposable live `$HOME/VM.bundle` working copy.
   9. Remove help shall state that deletion is permanent, explain protected snapshots and explicit live-source detachment, and explain why removing a logical parent does not invalidate children.
   10. Commit help shall explain its atomic snapshot-and-promote behavior and what remains unchanged when either operation fails.
   11. Help output shall display the currently configured live bundle, application, snapshot, recovery, and launcher paths when relevant.
   12. On user-correctable errors, the system shall print the smallest appropriate next command or corresponding help topic.
   13. Help examples shall clearly label permanent deletion and shall avoid force-killing the VM, booting a stored snapshot directly, or overwriting an existing snapshot.
   14. The system shall provide `vmctl doctor --help` and document how diagnostics verify installation, signing, entitlement, storage, live bundle, and shell-path readiness without mutating VM state.
   15. Automated tests shall verify that every supported command appears in the command index, has command-specific help, and is covered by at least one workflow or example where applicable.
