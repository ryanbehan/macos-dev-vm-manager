# Feature: Public Release and Turnkey Distribution

## Introduction

Prepare `vmctl` for publication as a professional public GitHub project and for turnkey use by developers on supported Apple silicon Macs. The public project will preserve the existing VM lifecycle and snapshot safety model while removing personally identifying and machine-specific assumptions, adding guided first-run setup, separating local developer signing from public distribution signing, and establishing repeatable privacy, quality, packaging, and release gates. VM bundles, macOS restore images, credentials, certificates, and user runtime data will remain local and will never be included in source control or public release artifacts.

## Requirements

1. User Story: As a public user, I want the repository and distributed artifacts to contain no personal or machine-specific information, so that the project can be used safely without exposing its original development environment.
   1. The system shall contain no personal names, personal email addresses, personal usernames, personal home-directory paths, Apple account identifiers, Apple team identifiers, certificate identifiers, device identifiers, private repository URLs, guest account names, or other personally identifying values in tracked files or distributed artifacts.
   2. The system shall use neutral placeholders in documentation, examples, fixtures, tests, and generated metadata.
   3. The system shall not hardcode an original developer's live bundle path, launcher path, snapshot name, signing identity, bundle identifier, network address, repository owner, or release destination.
   4. The system shall derive portable user paths from platform APIs or documented configuration, with environment-variable overrides retained where appropriate.
   5. The system shall generate and persist a locally administered virtual network address per VM instead of sharing one source-controlled address across installations.
   6. The project shall include an automated release-hygiene check that fails on prohibited personal path patterns, signing identifiers, credential material, private keys, VM artifacts, and unexpectedly large tracked files.
   7. Before the first public commit, the repository shall use a privacy-preserving commit author email and shall not introduce personally identifying author metadata that the maintainer has not explicitly approved for publication.
   8. Required copyright notices and third-party license attribution shall be preserved and shall not be treated as removable personal information.

2. User Story: As an existing `vmctl` user, I want public-release changes to preserve my current VM and snapshots, so that publication work cannot damage the environment that proved the tool.
   1. The system shall not automatically move, rename, clone, delete, or rewrite an existing live VM, snapshot, recovery artifact, or catalog during installation or upgrade.
   2. When legacy paths or metadata are detected, the system shall provide a read-only migration preview that lists exact source and destination paths and required storage before any change.
   3. A migration shall require an explicit execution command after preview and shall retain the existing transaction, containment, symlink, base, and live-source protections.
   4. If migration fails before commit, the system shall leave the prior installation usable or restore it automatically when safe.
   5. The existing permanent snapshot-removal semantics, immutable stored snapshots, independently loadable children, bounded rollback, and exceptional-only recovery storage shall remain unchanged.
   6. The project shall include automated migration tests using temporary fake bundles and shall never exercise migration against the maintainer's real VM as part of an ordinary test or build.

3. User Story: As a new developer, I want a guided first-run experience, so that I can reach a working VM without editing source code or reproducing the original developer's directory layout.
   1. The system shall provide a discoverable initialization command for an unconfigured installation.
   2. Initialization shall support importing an existing compatible `VM.bundle` without modifying the source bundle until the user approves the intended copy or adoption behavior.
   2.1. Import shall require the source VM to be shut down or shall require
        explicit clone-only approval to discard suspended state from the
        managed clone while preserving the source bundle.
   3. Initialization shall support creating a new VM from a compatible macOS restore image obtained from Apple, including an option to discover and download the latest image supported by the host.
   4. The system shall not bundle, mirror, commit, or publish a macOS restore image or installed VM disk.
   5. Before downloading or installing, the system shall display the restore-image source, estimated download size when available, disk-image allocation, destination, and minimum free-space requirement.
   6. The system shall derive installation CPU, memory, hardware-model, and minimum-memory requirements from the selected restore image and host capabilities rather than from the original machine.
   7. Initialization shall create unique platform data, auxiliary storage, machine identifier, and virtual network identity for the new VM.
   8. Initialization shall allow the user to select or accept neutral defaults for the VM location and initial base snapshot name.
   9. Initialization shall be resumable or shall fail with explicit cleanup instructions without leaving an apparently valid partial VM.
   10. After initialization, the system shall run non-mutating diagnostics and print the smallest next command needed to start the VM.

4. User Story: As a public user, I want a predictable user-scoped installation, so that I can run `vmctl` from any directory without maintaining a source checkout.
   1. The default installation shall place application code, configuration, state, snapshots, recovery data, and the live VM in documented user-scoped locations appropriate for macOS.
   2. Source code, generated application artifacts, and mutable VM data shall be stored separately so that updating the tool cannot overwrite VM data.
   3. The installer shall support a non-administrator installation path and shall not require disabling Gatekeeper or changing global security settings.
   4. The installer shall install a stable `vmctl` launcher and verify its resolution through the active shell.
   5. The installer shall not silently modify shell startup files; when a PATH change is necessary, it shall print the exact optional change or request explicit approval.
   6. The installer shall detect unsupported architecture, unsupported macOS version, missing runtime dependencies, insufficient storage, existing conflicting launchers, and incompatible existing configuration before changing installation state.
   7. The installed CLI shall report its version and the runner version, and shall reject incompatible CLI/runner combinations with recovery guidance.
   8. Reinstallation and upgrade shall be idempotent and shall preserve user configuration and VM data.
   9. Uninstallation shall remove program files separately from VM data and shall preserve all VM data by default unless the user issues a separately confirmed permanent-data-removal command.

5. User Story: As a source contributor, I want a portable and documented build, so that I can validate changes with my own Apple developer environment.
   1. The source build shall not depend on a named signing identity, team identifier, personal bundle identifier, or original machine path.
   2. Python 3.10 or newer shall be an explicit source-build and source-install runtime requirement for the initial public release.
   3. The Swift runner shall build with SwiftPM using a compatible Swift 6 toolchain and macOS SDK supplied by either Apple's Command Line Tools for Xcode package or a full Xcode installation.
   4. The source workflow shall not require opening Xcode, creating an Xcode project, selecting a development team in Xcode, or invoking `xcodebuild`.
   5. The source installer shall perform a non-mutating dependency preflight before building and shall report exact corrective steps for missing or incompatible architecture, macOS version, Command Line Tools, Swift compiler, macOS SDK, Python runtime, signing utility, APFS volume, or storage.
   6. When Apple developer tools are missing, the preflight shall direct the user to Apple's `xcode-select --install` workflow and shall stop safely until the user reruns the installer after installation completes.
   7. The default local source build shall use an ad hoc signature with Hardened Runtime and the required entitlements, without requiring a certificate, Apple developer account, team identifier, or provisioning profile.
   8. The source build shall accept an explicitly configured Apple Development signing identity as an optional alternative to ad hoc signing and shall validate that the selected identity is available before building.
   9. The source installer shall not create a certificate, install certificate material, modify Keychain trust, add a trusted root, disable Gatekeeper, or instruct the user to bypass macOS security controls.
   10. Local ad hoc signing, optional Apple Development signing, and public Developer ID signing shall be separate modes with separate validation and trust expectations.
   11. The source build documentation shall list the exact supported macOS, Apple silicon, Swift toolchain, Python runtime, APFS, storage, and signing prerequisites and shall explain that full Xcode is optional.
   12. The build shall provide one documented validation entry point that runs dependency preflight, static checks, Python tests, Swift tests, a release build, app-bundle validation, strict signature validation, and entitlement validation without booting or modifying a real VM.
   13. A separately gated source-install smoke test shall prove that an ad hoc signed runner can start and safely stop a dedicated disposable VM on every supported macOS release before that source-install path is declared supported.
   14. Tests shall use temporary homes, temporary VM bundles, and injected signing/process adapters and shall not depend on maintainer-specific files, certificates, snapshots, or environment variables.
   15. Build and test output intended for issue reports shall support redacting home paths and other local identifiers.
   16. The initial 0.1.0 source release shall support Apple silicon hosts
       running macOS 26.0 or newer. Earlier macOS releases shall remain
       unsupported until the complete real-VM smoke gate passes on each
       advertised major version.

6. User Story: As a developer downloading a release, I want a trusted macOS artifact, so that I can install and run the tool without Xcode or a local signing certificate.
   1. A public binary release shall contain a self-contained or explicitly dependency-managed `vmctl` CLI and a compatible `VMRunner.app`.
   2. The distributed app and all nested executable code shall be signed with an appropriate Developer ID identity, Hardened Runtime, and secure timestamp.
   3. The distributed runner shall contain only the entitlements required for virtualization and documented optional devices and shall not contain `get-task-allow`.
   4. The distributable archive shall be accepted by Apple's notarization service and shall have a stapled notarization ticket where the artifact format supports stapling.
   5. The release pipeline shall verify the final artifact with strict code-signature validation, Gatekeeper assessment, entitlement extraction, archive expansion, clean-install, launch-readiness, and checksum verification.
   6. Public signing certificates, private keys, certificate passwords, Apple credentials, notarization credentials, and keychain files shall never be committed, embedded in artifacts, or printed in logs.
   7. If release signing is automated, credentials shall be supplied through protected GitHub secrets with least-privilege workflow permissions and ephemeral keychain cleanup.
   8. Every release artifact shall have a versioned filename, SHA-256 checksum, release notes, and a documented minimum supported macOS and architecture.
   9. Ordinary local development builds shall not be represented as notarized public releases.

7. User Story: As a repository visitor, I want professional documentation and governance, so that I can understand, evaluate, use, and contribute to the project.
   1. The repository shall include a README with project purpose, compatibility, screenshots or terminal examples, architecture summary, installation, first-run setup, importing and creating a VM, everyday lifecycle commands, snapshot workflows, storage behavior, destructive-operation warnings, troubleshooting, limitations, privacy, and uninstall instructions.
   2. The README shall clearly state that the project does not distribute macOS, restore images, VM disks, Apple credentials, or guest credentials.
   3. The documentation shall explain APFS copy-on-write accounting, potentially large logical snapshot sizes, permanent removal, bounded rollback, and exceptional recovery storage.
   4. The documentation shall identify unsupported or intentionally absent integrations, including host-to-guest clipboard behavior unless such support is implemented and tested.
   5. The repository shall include an explicit open-source license selected by the maintainer before publication.
   6. The repository shall include `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `CHANGELOG.md`.
   7. The repository shall include issue and pull-request templates that request reproducible diagnostics while warning users to redact usernames, home paths, VM names, guest details, and credentials.
   8. The repository shall document support boundaries and shall avoid implying affiliation with or endorsement by Apple.
   9. Command help and repository documentation shall use the same command names, path model, safety language, and version requirements.

8. User Story: As a maintainer, I want automated public-repository quality gates, so that unsafe or nonportable changes cannot be released accidentally.
   1. Pull-request validation shall run the complete Python and Swift test suites on a supported macOS runner.
   2. Pull-request validation shall run shell static analysis and shall fail on warnings in project-owned shell scripts unless a documented suppression is reviewed.
   3. Pull-request validation shall scan tracked content and generated source archives for secrets, personal paths, signing identifiers, prohibited VM artifacts, and excessive file sizes.
   4. Pull-request validation shall build the unsigned or development-mode runner and verify app structure and required entitlement declarations without requiring public release credentials.
   5. Release validation shall be separate from untrusted pull-request execution and shall not expose signing or notarization secrets to forked code.
   6. Automated tests shall cover clean initialization, existing-bundle import, safe migration preview and execution, install, upgrade, uninstall-with-data-preservation, version compatibility, and representative failure recovery.
   7. Stateful real-VM smoke tests shall be explicitly gated, shall operate only on a dedicated disposable test VM, and shall never run against a contributor's or maintainer's normal VM by default.
   8. All required checks shall pass from a clean checkout before a version tag or release can be published.

9. User Story: As a maintainer, I want reproducible GitHub publication and releases, so that the public repository remains trustworthy and maintainable.
   1. The local repository shall be connected to the explicitly confirmed public GitHub repository before publication, and the remote's existing history shall be reviewed before the first push.
   2. The initial public history shall contain only reviewed source, specifications, tests, documentation, and automation files; ignored local runtime data shall not be force-added.
   3. The repository shall define a stable project name, bundle identifier namespace, versioning policy, supported release channels, and release artifact naming convention without embedding a personal identity in code.
   4. Releases shall be created from immutable version tags after required checks pass.
   5. The repository shall enable appropriate branch protection, required checks, dependency/security alerts, secret scanning, and push protection when available.
   6. GitHub Actions workflows shall declare least-privilege permissions, pin third-party actions to reviewed immutable revisions, and avoid running privileged release jobs for untrusted changes.
   7. Release generation shall operate from tracked files or a clean checkout and shall prove that VM bundles, restore images, runtime state, recovery data, local application bundles, credentials, and development caches are absent.
   8. The project shall publish release notes describing user-visible changes, compatibility changes, migration requirements, known limitations, and checksum verification.
   9. A first public release shall not be published until a clean-machine installation and first-run workflow succeeds using only the public documentation and release artifacts.

10. User Story: As a privacy-conscious developer, I want transparent local behavior, so that I understand what data leaves my machine.
   1. The tool shall operate locally without telemetry, analytics, crash-report uploads, or remote control unless a future separately approved feature explicitly adds them.
   2. Network access shall be limited to documented user-requested operations, such as obtaining restore-image metadata or downloading a restore image from Apple.
   3. The tool shall display the destination and source before a network download and shall not upload VM data, snapshots, guest information, logs, or configuration.
   4. Diagnostics shall be local and non-mutating and shall provide a redacted sharing mode suitable for public issue reports.
   5. Documentation shall distinguish host configuration, guest configuration, Apple service interactions, and GitHub release downloads.
