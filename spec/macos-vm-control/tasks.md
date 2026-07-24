# Implementation Plan: macOS VM Control

- [x] 1. Establish the existing CLI, catalog, lifecycle, runner, installer, and automated-test foundation.
  - Preserve the working Python command architecture, Swift/AppKit Virtualization runner, signed staged application, shell launcher, snapshot/base commands, diagnostics, and injected test adapters already implemented.
  - Treat the old recoverable-remove and accumulated-live-backup behavior as implementation to replace, not as approved behavior to preserve.
  - References: Requirements 1.1–1.7, 2.1–2.10, 4.1–4.10, 6.1, 6.3–6.4; Design “Architecture,” “Components and Interfaces,” and “Testing Strategy.”

- [x] 2. Implement permanent-deletion safety primitives test-first.
  - Write failing tests for exact-root containment, path traversal, symlink targets, deletion-root rejection, live-bundle rejection, protected-path rejection, missing targets, and successful recursive deletion of an eligible fake bundle.
  - Add one store-layer deletion helper used by snapshot removal, transaction cleanup, failed-commit cleanup, and the separately approved legacy migration.
  - Require callers to declare the expected root and target category so unrelated files cannot be deleted through a generic path.
  - References: Requirements 5.1–5.5, 7.1–7.6; Design “Permanent remove” and “Safety rules.”

- [x] 3. Implement the transaction journal and interrupted-operation reconciliation test-first.
  - Write failing tests for atomic journal creation and each `prepared`, `displaced`, `activated`, and `committed` transition.
  - Cover interruption states where the temporary clone, live bundle, rollback bundle, metadata, or journal is missing or partially advanced.
  - Implement deterministic reconciliation that restores the displaced live bundle before commit, completes validated post-commit cleanup, and preserves artifacts under `recovery/failed` only when safe rollback or cleanup cannot complete.
  - Run reconciliation before every mutating command while holding the existing exclusive lock.
  - References: Requirements 3.2–3.9, 4.3, 5.2–5.5, 6.2; Design “Load/reset,” “Transaction journal,” and “Exceptional recovery only.”

- [x] 4. Replace load, revert, and reset backup accumulation with bounded rollback transactions.
  - Write failing command tests proving that a successful load or reset leaves no `recovery/pending` entry and no transaction journal.
  - Test source validation, fresh-clone activation, metadata commit, automatic pre-commit rollback, post-commit cleanup, `revert` alias equivalence, and base-driven reset.
  - Remove creation of timestamped `recovery/live` backups from normal operation and route only uncleanable rollback or cleanup failures to `recovery/failed`.
  - Verify stored snapshots remain immutable and independently loadable.
  - References: Requirements 3.1–3.9, 6.2, 7.11; Design “Load/reset” and “Bounded rollback.”

- [x] 5. Replace recoverable removal and undeletion with permanent snapshot removal.
  - Write failing tests for permanent bundle/metadata deletion, the permanent-deletion message and exact path, base protection, live-source protection, stopped-only `--detach-live`, and child independence after parent deletion.
  - Remove the `undelete` command, removed-snapshot catalog scanning, `removedAt` metadata, and `list --all` or `tree --all` recycle-bin behavior.
  - Render missing logical parents as synthetic `[deleted]` nodes derived only from surviving child metadata.
  - Ensure legacy `recovery/removed` entries are ignored by the active snapshot catalog and are accessible only to the migration inventory.
  - References: Requirements 2.9–2.10, 7.1–7.6, 7.15; Design “Permanent remove,” “Snapshot metadata,” and command interface.

- [x] 6. Make snapshot and commit failures clean up disposable data safely.
  - Write failing tests proving routine snapshot failures delete validated partial clones instead of retaining them and preserve an artifact only when cleanup itself fails.
  - Test atomic commit success, unchanged prior base on promotion failure, and permanent deletion of a snapshot created solely by a failed commit.
  - Reuse the permanent-deletion helper and print any exceptional failed-artifact path.
  - References: Requirements 2.1–2.5, 5.3–5.5, 7.12–7.15; Design “Snapshot,” “Commit,” and “Safety rules.”

- [x] 7. Update CLI parsing and the complete help system for the approved storage model.
  - Write failing coverage tests proving every supported command has command-specific help and appears in the top-level index while `undelete` and removed-catalog options are rejected.
  - Explain permanent removal, protected base/live-source snapshots, explicit detachment, deleted-parent tree rendering, transaction-scoped rollback, exceptional recovery, and the need to snapshot live state before loading if it must be retained.
  - Update lifecycle, snapshots, branching, base, and recovery workflows and ensure errors print the smallest relevant next command.
  - References: Requirements 4.1, 7.1–7.13, 8.1–8.15; Design “Help system.”

- [x] 8. Update configuration, initialization, status, and diagnostics for bounded recovery storage.
  - Write failing tests for initialization of `recovery/pending` and `recovery/failed` without creating new `recovery/live` or `recovery/removed` directories.
  - Update status and doctor output to report an active transaction, pending rollback, exceptional failed artifacts, and legacy-recovery presence without mutating or deleting data.
  - Preserve environment overrides, launcher behavior, current base, current live origin, and stale-runtime handling.
  - References: Requirements 4.2–4.10, 6.3–6.4, 7.7–7.11, 8.11, 8.14; Design “Project layout,” “Runtime status,” and command interface.

- [x] 9. Implement a separately gated legacy-recovery migration utility test-first.
  - Add an inventory-only default that records exact candidate paths, categories, entry counts, logical sizes, current free space, and a manifest digest without deleting anything.
  - Write tests proving execution refuses a running VM, a changed or unapproved manifest, symlinks, path escapes, protected/live paths, and candidates outside legacy `recovery/live` or `recovery/removed`.
  - Require an explicit execution flag plus the unchanged reviewed manifest, delete only its allowlisted candidates through the shared deletion helper, and report `df` before and after without treating `du` as physical reclaimed space.
  - Do not execute this utility against real legacy data as part of implementation; each real cleanup pass requires separate approval of its manifest.
  - References: Requirements 5.3–5.4, 7.16; Design “Legacy recovery migration.”

- [x] 10. Run and repair the complete automated validation suite.
  - Run focused tests after each implementation task, then the full Python suite, Swift suite, release build, app staging, strict signature verification, entitlement extraction, installer tests, help coverage, and `vmctl doctor`.
  - Verify normal test runs create no persistent `recovery/live` or `recovery/removed` data and leave no pending transaction or journal.
  - Fix only failures within the approved requirements and rerun the smallest relevant suite before the complete suite.
  - References: Requirements 6.1–6.4, 7.15, 8.15; Design “Testing Strategy” and “Build and signing verification.”

- [x] 11. Run the guarded automated real-VM smoke sequence and restore the intended stopped state.
  - Record the original base, live origin, runtime state, configured paths, and free space before mutation; require the VM to be stopped and preserve current live work as an explicit named snapshot when needed.
  - Exercise start, stop, shutdown, snapshot, load/revert, branch, permanent removal of uniquely named smoke snapshots, promote, reset, commit, shell-path invocation, and interrupted-transaction reconciliation.
  - Restore the intended base and live source, leave the VM stopped, verify all smoke snapshots are removed, and verify `recovery/pending` and the transaction journal are absent.
  - Never delete pre-existing named snapshots or legacy recovery data during the smoke test.
  - References: All requirements; Design “Real-VM smoke sequence.”
