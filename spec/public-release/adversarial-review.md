# Adversarial Review: Public Release

## Scope

This review treats every source, configuration, test, specification, script, generated app, runtime record, and potential release archive as hostile to privacy and portability. It asks whether a clean checkout can expose the original development machine, signal or delete an unintended target, bypass a macOS trust decision, follow an attacker-controlled path, or accidentally publish Apple software or VM data.

The review is non-destructive. It does not launch or modify the VM, migrate data, change signing configuration, alter Git metadata, or publish anything.

## Baseline evidence

- The repository has no commits and no configured remote.
- All current project files are untracked; generated app, build output, snapshots, recovery, state, and bytecode are ignored only in their current directories.
- The Python suite passes 81 tests.
- The Swift suite passes 4 tests.
- ShellCheck reports one project-shell warning in the legacy installer.
- No candidate source file exceeds 1 MiB and no candidate source path is a symlink.
- Pattern scans found no private key, common provider token, password assignment, private repository URL, host name, or computer name in candidate source files.
- The project currently has no third-party package dependencies; Python uses the standard library and Swift links system frameworks.

Passing tests are not release evidence for the findings below because the current suites encode several machine-specific and insecure behaviors as expected behavior.

## Findings

### AR-01 — Personal and machine-specific values are present in public candidates

**Severity:** Critical publication blocker

Candidate source contains an original login name, absolute home paths, personal signing subject, certificate identifier, personal bundle-identifier namespace, dated local baseline name, and machine-specific help/examples.

Affected areas include:

- `src/vmctl/config.py`
- `src/vmctl/helptext.py`
- `src/vmctl/bootstrap.py`
- `script/install.sh`
- `script/build_runner.sh`
- `tests/test_scripts.py`
- `spec/macos-vm-control/requirements.md`
- `spec/macos-vm-control/design.md`

The generated local app additionally embeds a personal signing authority and Apple team identifier. The ignored runtime state contains local paths and VM/snapshot names.

**Required remediation:** Replace tracked values with portable derivation or neutral fixtures, rebuild with ad hoc signing, sanitize historical specifications, scan generated Mach-O/app metadata, and use an explicitly approved privacy-safe author identity for the first public commit.

### AR-02 — Apple-derived source lacks its required attribution in this repository

**Severity:** Critical publication blocker

The Swift VM configuration and runner are adapted from Apple’s “Running macOS in a virtual machine on Apple silicon” sample. The current official archive contains an Apple copyright notice and MIT license, but this repository has neither a project license nor the Apple notice.

**Required remediation:** Add the project MIT license, the exact Apple sample license, a third-party notice with source/checksum/provenance, and adapted-file comments. Replace any portion whose licensing provenance cannot be established.

### AR-03 — Ignore rules do not protect Apple and VM artifacts outside known directories

**Severity:** Critical publication blocker

The current ignore file protects `app/`, `snapshots/`, `recovery/`, and `state/`, but a root or nested `VM.bundle`, IPSW, disk image, saved state, certificate archive, provisioning profile, private key, `.env` file, or temporary keychain is not generally ignored.

**Required remediation:** Add artifact- and credential-oriented patterns independent of location and enforce the same rules against tracked files and generated source archives so `git add -f` cannot bypass the release gate.

### AR-04 — The VM network identity is copied from Apple’s sample

**Severity:** High

The runner embeds one fixed virtual MAC address. Every installation would share it, and the value is also embedded in the built executable.

**Required remediation:** Generate and persist one locally administered unicast address per VM, migrate legacy bundles through staging or explicit adoption, and scan binaries for the old fixed value.

### AR-05 — Launch removes quarantine metadata

**Severity:** High

`vmctl start` currently removes `com.apple.quarantine` before every launch. This turns a macOS trust decision into normal runtime mutation and conflicts with the public contract not to bypass Gatekeeper.

**Required remediation:** Clear inherited metadata only inside a newly created source-build staging directory before signing. Installed artifacts fail closed when quarantine or signature state is unexpected.

### AR-06 — Runtime process identity is verified only by basename

**Severity:** High

Before sending suspend or shutdown signals, the lifecycle code accepts any live PID whose `comm` basename is `VMRunner`. An unrelated or substituted process with that name could receive a signal.

**Required remediation:** Validate PID, effective user, canonical executable path, installed release identity, and runtime-record permissions immediately before each signal. Test same-name wrong-path and PID-reuse cases.

### AR-07 — VM and runtime data can be readable by other local accounts

**Severity:** High

Current VM directories are mode `0755`, disk images are mode `0644`, and the Swift runtime record is mode `0644`. On a multi-user Mac, another local account may be able to traverse and read VM data or local paths.

**Required remediation:** Use private managed directories (`0700`) and data/state files (`0600`), preview permission changes for adopted external bundles, and test under a permissive umask.

### AR-08 — Bundle and catalog validation follows symlinks

**Severity:** High

Required bundle artifacts are accepted through `Path.is_file()`, and catalog enumeration accepts directories through `Path.is_dir()`. Both follow symlinks. A hostile imported bundle or snapshot entry could refer outside the managed roots.

**Required remediation:** Reject symlinked roots, catalog entries, and required artifacts; require regular direct-child files; enforce ownership and containment; and add hostile-bundle tests.

### AR-09 — Entitlement validation is a text heuristic

**Severity:** High

The builder and diagnostics search output for the virtualization key and a `<true/>` token rather than parsing the entitlement property list. An unrelated true value could produce a false pass, and excessive entitlements are not rejected.

**Required remediation:** Parse the plist, compare exact approved keys and Boolean values, reject `get-task-allow`, and make microphone access an explicit documented feature rather than an unexamined default.

### AR-10 — The legacy installer writes state before completing preflight

**Severity:** Medium

The current installer initializes directories/catalog metadata before it checks for a conflicting launcher. A failed install can therefore mutate local state despite reporting installation failure.

**Required remediation:** Complete all non-mutating dependency, path, conflict, signing-mode, and storage checks before the first write; then use staged, journaled, versioned installation.

### AR-11 — Diagnostics and smoke output can disclose local identifiers

**Severity:** Medium

Status, diagnostics, system-framework errors, and the guarded smoke report may emit absolute paths, original snapshot names, signing details, or other local values. No share-mode redaction exists yet.

**Required remediation:** Implement one terminal-safe redaction library and use it for `doctor --share`, shareable failure records, CI output, smoke reports, and issue guidance.

### AR-12 — Ignored local data remains one force-add away from disclosure

**Severity:** Medium

Ignored state and snapshot metadata currently contain personal paths and local VM names. Ignore rules prevent ordinary addition but not a forced add, archive script mistake, or future path relocation.

**Required remediation:** Add a content-aware tracked/archive hygiene gate and verify releases from a clean checkout or an explicit tracked-file manifest.

### AR-13 — The current install layout is source-tree coupled

**Severity:** Medium

The launcher points back to the mutable development checkout, and diagnostics expect that project-local target. Moving or deleting the checkout breaks the installed command and risks mixing program updates with VM state.

**Required remediation:** Install immutable versioned program releases separately from configuration and VM data, then atomically switch a stable launcher.

### AR-14 — The first commit would inherit a personal global Git identity

**Severity:** Critical publication blocker

The repository has no commits, but the active global Git author name and email are personal. If used unchanged, the first public commit permanently records them even if source content is sanitized.

**Required remediation:** Require explicit approval of a privacy-safe repository-local author identity before the first commit and scan the complete public commit range before push.

## Positive controls to preserve

- Destructive snapshot operations already use typed deletion categories, direct-child containment, base/live protections, and extensive temporary-directory tests.
- Load/reset use bounded transaction recovery instead of retaining successful rollback bundles.
- Commands use argument arrays rather than shell interpolation for process execution.
- The project currently has no Git history, remote, public release, or third-party package dependency to unwind.
- No real VM was touched by this review.

## Release decision

**Not ready for a public commit or release.**

The implementation plan must close AR-01 through AR-14, rerun the adversarial scans on tracked files and generated artifacts, and produce a clean source archive before publication can be considered.
