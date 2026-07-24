# Changelog

All notable user-visible changes are documented here. The project follows
Semantic Versioning.

## [Unreleased]

- Prepared a portable source-first installation for Apple-silicon Macs.
- Added guided existing-bundle import and Apple restore installation.
- Added fail-closed suspended-bundle import with explicit clone-only
  `--discard-saved-state` recovery.
- Added immutable snapshot, base, migration, and permanent-removal workflows.
- Added ad hoc local signing with strict entitlement verification.
- Added privacy hygiene, redacted diagnostics, source archives, and CI gates.
- Added release-hygiene support for extracted source archives without Git
  metadata.
- Preserved the original VM startup/restore error when the runner terminates
  after a launch failure.
- Constrained the initial validated host range and hosted CI to Apple silicon
  macOS 26 or newer; earlier hosts remain unsupported until real-VM smoke
  coverage is available.

## [0.1.0] - Unreleased

- Initial public source release candidate.
