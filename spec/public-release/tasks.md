# Implementation Plan: Public Release and Turnkey Distribution

- [x] 1. Establish licensing and provenance before modifying adapted source.
  - Add a root MIT `LICENSE` for project-owned work.
  - Add the exact current Apple sample license at `LICENSES/Apple-Sample-Code-MIT.txt`.
  - Add `THIRD_PARTY_NOTICES.md` with the official sample URL, archive checksum, retrieval date, adapted file map, and no-endorsement statement.
  - Compare each adapted Swift file with the reviewed official archive; add concise provenance comments or replace portions whose applicable license cannot be established.
  - Add tests that fail when the Apple notice, provenance mapping, or adapted-file marker is absent or modified unexpectedly.
  - Acceptance evidence: license files match reviewed sources; provenance check passes; no Apple SDK, framework, binary, artwork, IPSW, or VM artifact is present.
  - References: Requirements 1.8, 3.4, 7.2, 7.5, 7.8; Design “Apple sample-code provenance” and “Apple software and SDK boundary”; Review AR-02.

- [x] 2. Build the release-hygiene gate and strengthen ignore coverage test-first.
  - Add failing fixtures for personal home paths, login names, emails, signing subjects, team identifiers, fixed network addresses, secrets, private keys, certificate archives, provisioning profiles, `.env` files, VM bundles, IPSWs, disk/saved-state artifacts, generated apps, runtime state, oversized files, and escaping symlinks.
  - Expand `.gitignore` so prohibited Apple/VM/signing artifacts are protected anywhere in the checkout, not only under current runtime directories.
  - Implement `script/check_release_hygiene.py` for tracked files, Git author metadata, generated source archives, and optional Mach-O/app string inspection.
  - Permit only the exact reviewed Apple license/attribution text in allowlisted files.
  - Run the scanner from a clean tracked-file manifest and prove a force-added prohibited fixture fails.
  - Acceptance evidence: all positive fixtures fail with redacted diagnostics; clean repository and generated archive pass.
  - References: Requirements 1.1–1.8, 8.3, 9.2, 9.7; Design “Repository hygiene”; Review AR-01, AR-03, AR-12, AR-14.

- [x] 3. Sanitize every public candidate and neutralize defaults.
  - Remove personal names, usernames, home paths, certificate/team identifiers, personal bundle namespaces, machine-specific snapshot names, and original-machine examples from source, scripts, tests, help, environment files, and both specification sets.
  - Preserve historical product decisions using `$HOME`, temporary paths, `initial`, `dev-ready`, and other neutral fixtures.
  - Replace bundle identifiers with the approved `dev.vmctl.*` namespace.
  - Ensure generated app metadata and release binaries contain no original personal or machine-specific strings.
  - Do not modify ignored live VM, snapshot, recovery, or state data as part of source sanitization.
  - Acceptance evidence: known-value scan, generic PII scan, generated-app scan, and clean archive scan report no prohibited match.
  - References: Requirements 1.1–1.4, 1.7, 5.1, 7.9; Design “Portable Filesystem Layout” and “Repository hygiene”; Review AR-01, AR-14.

- [x] 4. Implement portable configuration and versioned program/data separation test-first.
  - Derive defaults from `Path.home()` and macOS user-library conventions with CLI, environment, installed config, and default precedence.
  - Add schema-validated `config.json`, install/release manifests, root `VERSION`, CLI/runner protocol version, and neutral initial base name.
  - Separate immutable versioned program releases from mutable VM data and atomically manage `current`.
  - Preserve existing `VMCTL_*` overrides without allowing them to bypass containment or managed-root checks.
  - Acceptance evidence: temporary-home tests install and run from unrelated directories; moving/removing the source checkout does not break the installed command; existing real VM paths remain untouched.
  - References: Requirements 2.1–2.4, 4.1–4.9, 5.14; Design “Portable Filesystem Layout,” “Version contract,” and “Portable configuration”; Review AR-10, AR-13.

- [x] 5. Harden local permissions, bundle validation, metadata, and filesystem primitives test-first.
  - Add hostile fixtures for symlinked bundle roots, symlinked/nonregular artifacts, catalog symlinks, path escapes, mismatched directory/metadata names, malformed schemas, terminal controls, broken destination symlinks, and permissive umasks.
  - Reject symlinked or outside-root artifacts and require regular direct-child VM files.
  - Validate metadata schema, bounded printable values, name-directory equality, ownership, and containment before display or mutation.
  - Create managed data directories as `0700` and sensitive files as `0600`; preview permission changes before touching adopted external data.
  - Review deletion and move/clone operations for time-of-check/time-of-use swaps and use no-follow or descriptor-relative operations where required.
  - Acceptance evidence: hostile fixtures cannot escape managed roots or expose data; managed VM disks and state are not group/world-readable.
  - References: Requirements 1.4, 2.1–2.6, 4.1, 8.6; Design “Local filesystem and process trust”; Review AR-07, AR-08.

- [x] 6. Replace the fixed network identity with a per-VM artifact test-first.
  - Generate a cryptographically random locally administered unicast MAC address for each new VM.
  - Persist `NetworkMACAddress` inside the VM bundle and preserve it across clones and snapshots.
  - Derive a stable legacy value from machine identity only for read-only planning or after explicit staged/adopt approval.
  - Reject invalid, multicast, globally administered, duplicate, or symlinked network-identity artifacts.
  - Acceptance evidence: independent VM fixtures receive different valid addresses; snapshot/load retains identity; source and binaries contain no fixed sample address.
  - References: Requirements 1.5, 3.7; Design “Per-VM network identity”; Review AR-04.

- [x] 7. Harden process control, signing validation, entitlements, and quarantine handling test-first.
  - Require PID liveness, current-user ownership, canonical executable path, active release identity, and a private runtime record immediately before suspend/shutdown signals.
  - Cover same-name wrong-path processes, stale/reused PIDs, malformed records, symlinked records, and permission mismatches.
  - Remove launch-time quarantine deletion; clear inherited attributes only in a unique generated staging directory before signing.
  - Parse entitlement plists and compare exact approved keys/values; require virtualization, reject `get-task-allow`, and make audio input an explicit documented option.
  - Verify staged and installed apps with strict signature checks; sign nested helper first and outer app last.
  - Acceptance evidence: hostile runtime/signature fixtures fail closed; ad hoc source app passes strict verification without a certificate; no Gatekeeper bypass instructions or runtime mutation remain.
  - References: Requirements 5.7–5.10, 6.2–6.6, 10.1; Design “App staging and signing modes” and “Local filesystem and process trust”; Review AR-05, AR-06, AR-09.

- [x] 8. Add the SwiftPM VM installation helper and VM-independent tests.
  - Add `VMInstallerCore` and `VMInstaller` products without introducing an Xcode project or third-party dependency.
  - Implement restore-image inspection, supported CPU/memory/hardware requirements, unique platform artifacts, disk creation, progress records, cancellation/failure records, and version/protocol output.
  - Package the helper under `VMRunner.app/Contents/Helpers` and include it in inside-out signing and validation.
  - Keep VM-independent logic testable without downloading an IPSW or starting a VM.
  - Acceptance evidence: Swift package builds with the selected Command Line Tools, all core tests pass, and staged helper/app signatures and entitlements validate.
  - References: Requirements 3.3–3.7, 5.3–5.4, 5.12; Design “Swift package products” and “Fresh install.”

- [x] 9. Implement non-mutating source preflight and versioned source installation test-first.
  - Add shell-only Python detection followed by Python preflight for arm64, macOS, Command Line Tools, Swift/SDK, Python 3.10+, signing tools, APFS, storage, writable paths, and launcher conflicts.
  - Ensure every check completes before the first write and print the exact `xcode-select --install` walkthrough when tools are missing.
  - Implement `install-from-source.sh` with Python/Swift tests, release build, ad hoc signing by default, staged validation, atomic version activation, stable launcher, and installed doctor.
  - Keep optional Apple Development and future Developer ID modes explicit; never create certificates or modify Keychain trust.
  - Acceptance evidence: missing/conflicting dependency fixtures make no writes; clean temporary-home install is idempotent; installed tool runs after source removal.
  - References: Requirements 4.3–4.8, 5.1–5.12; Design “Source preflight” and “Versioned source installation”; Review AR-10, AR-13.

- [x] 10. Implement guided initialization, import, and Apple restore workflows test-first.
  - Add `vmctl init`, clone/adopt import planning, and fresh install with `latest` or local restore image.
  - Keep import sources read-only until confirmation and operate on staging bundles.
  - Show Apple source/local path, download/cache/destination, expected size, disk allocation, and free-space requirements before network or disk mutation.
  - Download only the URL returned by Apple's API, validate before activation, and remove cached IPSW by default after success.
  - Never commit, archive, mirror, upload, or distribute an IPSW or installed VM.
  - Acceptance evidence: fake import/install transactions reconcile safely; prohibited Apple/VM artifacts are absent from tracked files and archives.
  - References: Requirements 3.1–3.10, 10.2–10.5; Design “Initialization command” and “Apple software and SDK boundary.”

- [x] 11. Implement migration, upgrade, and uninstall safety test-first.
  - Add digest-bound read-only migration plans and explicit apply for existing installations without automatic data movement or deletion.
  - Preserve legacy VM/snapshot data in place by default and keep existing permanent-removal semantics unchanged.
  - Implement atomic program upgrade and default uninstall that removes only manifest-owned program paths.
  - Keep data purge a separately confirmed exact-path operation with stopped-state and containment checks.
  - Acceptance evidence: temporary legacy fixtures migrate safely; failed operations leave prior installation usable; uninstall preserves all data by default.
  - References: Requirements 2.1–2.6, 4.8–4.9; Design “Existing-installation migration” and “Upgrade and uninstall.”

- [x] 12. Implement redacted diagnostics, complete help, and professional documentation.
  - Add one terminal-safe redaction library and `vmctl doctor --share`.
  - Redact home/login paths, VM/snapshot names, signer/team identity, guest details, and terminal controls from shareable output.
  - Update help for dependency walkthroughs, initialization, Apple media/license boundaries, signing modes, migration, upgrade, uninstall, snapshots, permanent removal, APFS accounting, limitations, and clipboard behavior.
  - Add `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, and issue/PR templates.
  - Acceptance evidence: documentation walkthrough works from a clean checkout; redaction fixtures contain no local identifier; command/help registry remains synchronized.
  - References: Requirements 5.11, 5.15, 7.1–7.9, 10.4–10.5; Design “Diagnostics and redaction”; Review AR-11.

- [x] 13. Add least-privilege CI and reproducible source-release preparation.
  - Add macOS pull-request CI for hygiene, ShellCheck, Python/Swift tests, release build, ad hoc staging, exact entitlement/signature checks, temporary-home workflows, and archive inspection.
  - Pin third-party actions to reviewed immutable revisions and grant read-only permissions unless a job explicitly needs more.
  - Add a tag workflow that creates a scanned source archive, checksums, and draft release assets without signing secrets or automatic publication.
  - Keep future Developer ID/notarization work separate, environment-protected, and disabled until credentials and publication are separately approved.
  - Acceptance evidence: untrusted PR jobs have no secrets/write token; clean tag simulation creates only reviewed source assets.
  - References: Requirements 8.1–8.8, 9.3–9.8; Design “CI and release workflows.”

- [x] 14. Run the full automated and adversarial validation matrix.
  - Run the hygiene fixtures, ShellCheck, all Python tests, all Swift tests, release build, source preflight, app staging, strict signature/entitlement checks, temporary-home install/init/migrate/upgrade/uninstall tests, and source-archive scan.
  - Re-run known-machine-value scans, generic PII/secret scans, hostname/Git identity checks, ignored-artifact tests, permission checks, hostile symlink/metadata tests, process-substitution tests, and Mach-O string scans.
  - Verify no test touches the maintainer's real VM, current snapshots, recovery, state, shell files, Keychain, Git identity, remote, or public repository.
  - Acceptance evidence: every required automated gate passes with recorded commands and no residual files outside test roots.
  - References: Requirements 5.12–5.15, 8.1–8.8; Design “Testing Strategy”; Review AR-01–AR-14.

- [x] 15. Perform guarded clean-machine and disposable-VM validation without publishing.
  - Validate source installation and documentation on a clean supported Apple silicon Mac account using only public-candidate files.
  - Run real VM operations only against a separately identified disposable test VM after explicit execution confirmation and storage review.
  - Prove import, start, suspend/resume, shutdown, snapshot/load/reset/remove, and default uninstall preserving data.
  - Audit the complete candidate commit range and source archive one final time.
  - Do not commit, push, configure a remote, create a GitHub release, or use Developer ID/notarization credentials without separate explicit approval.
  - Acceptance evidence: clean-machine report, disposable-VM before/after report, final hygiene report, archive manifest, and checksums.
  - References: Requirements 5.13, 8.7–8.8, 9.1–9.9; Design “Guarded real-VM tests,” “Release validation,” and “Publication Boundary.”
  - 2026-07-24 evidence: final source-archive installation under a new isolated
    empty home passed. The macOS 26 disposable clone passed fail-closed
    suspended import, explicit clone-only saved-state discard, cold start,
    suspend/resume, bounded guest-shutdown handling, snapshot, load, remove,
    promote, reset, commit, interrupted-transaction recovery,
    uninstall-preserve, reinstall, and exact-path purge. Exact executable-path
    and open-handle checks proved the maintainer VM stayed stopped and shut down;
    its disk size, inode, and modification time and its small platform-file
    hashes were unchanged. The initial support contract is macOS 26+ until
    equivalent real-VM evidence exists for earlier releases.
