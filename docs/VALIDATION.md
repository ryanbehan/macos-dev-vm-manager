# Public release validation

Validation date: 2026-07-24

This report covers the source candidate and a disposable APFS-cloned VM on one
Apple silicon host running macOS 26.4.1. The initial v0.1.0 support range is
Apple silicon on macOS 26.0 or newer. It did not download an IPSW, alter shell
startup files or Keychain, create a commit, configure a remote, push, or publish
a release.

## Passed automated gates

- `shellcheck script/*.sh`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
  - 102 tests passed
- `swift test --package-path runner`
  - 9 tests passed
- `./script/build_runner.sh --signing adhoc`
- `python3 script/verify_app.py app/VMRunner.app`
  - strict nested and outer signature checks passed
  - bundle identifier `dev.vmctl.runner`
  - ad hoc Hardened Runtime signature
  - exact virtualization-only entitlement set
- `python3 script/check_release_hygiene.py --allow-author`
- Deterministic source archive generated twice with the same checksum
- Source archive checksum and archive hygiene scan passed
- Adversarial scans found no current login, home path, hostname, Git name, Git
  email, known machine snapshot name, personal bundle namespace, fixed sample
  network address, credential pattern, VM artifact, or local path in public
  candidates, the source archive, or generated app binaries.

## Clean source-archive installation

- The scanned archive contained 81 regular source files and no symlinks,
  binaries, VM data, Apple restore media, credentials, or generated app bundle.
- Installation ran from the extracted archive under an empty isolated `HOME`
  and a minimal environment.
- The first minimal-path attempt selected macOS's Python 3.9 and stopped before
  program or VM writes, as required. The documented Python 3.10+ dependency was
  then supplied explicitly.
- Dependency preflight, all tests, release build, nested and outer ad hoc
  signing, exact entitlement validation, and installed diagnostics passed.
- The hygiene scanner now supports both Git checkouts and extracted archives;
  the first clean-archive attempt exposed and fixed the prior Git-only
  assumption.
- The installed command ran outside the source directory.

## Disposable VM lifecycle

- A suspended source was rejected by default. Clone import with
  `--discard-saved-state` made no writes during preview, required an explicit
  `--yes`, removed saved state only from the staged clone, and preserved the
  source saved-state checksum.
- Clone import left its source in place, generated a new virtual network
  identity, created an independent initial base, and passed `doctor --share`.
- Start, suspend, resume, guest-requested shutdown, snapshot, load, branch
  removal, promote, reset, commit, interrupted-transaction reconciliation, and
  cleanup passed.
- The guarded smoke run restored its original disposable base and live-source
  metadata with no smoke snapshots, pending rollback, transaction, or failed
  recovery residue.
- The guest shutdown request waited for the locked guest's normal power
  confirmation and used the designed bounded safe-stop fallback. The request
  was accepted, the timeout preserved the running VM for confirmation, and the
  harness then suspended it without force termination. A prior disposable run
  selected Shut Down in the guest and verified guest exit.
- Default uninstall removed program files while preserving the disposable live
  VM and all 19 catalog/data files. Reinstallation from the extracted archive
  passed diagnostics against that preserved data. A separately approved
  exact-path purge then removed only the disposable data root.

## Isolation repeat and release decision

During UI confirmation, an automation lookup by the shared
`dev.vmctl.runner` bundle identifier also launched the maintainer's
project-local runner. The exact process was identified by executable path and
open file handles, safely suspended, and then shut down using a freshly built
isolated runner. The normal VM is again stopped and shut down with its original
base and live-source selections and no transaction or recovery residue.

The complete procedure was repeated from the final extracted source archive
under a new empty isolated `HOME`. Before every VM start, the only `VMRunner`
process was identified by exact executable path and its Virtualization XPC
process was verified against the disposable disk. The normal VM had no runner
or open disk handle. After the repeat, the normal disk retained the exact same
size, inode, and modification timestamp, and its hardware model, machine
identifier, and auxiliary-storage SHA-256 hashes were unchanged. The normal VM
remained stopped and shut down throughout the repeat.

After cleanup, the source installer staged the maintainer's runner under the
user Application Support directory. A digest-bound migration preview reported
zero required storage, no data movement, and no deletions; applying it wrote
only the private installed configuration and stable launcher. Installed
diagnostics now pass without quarantine while the existing live VM, snapshots,
base, state, and recovery paths remain in place.

The clean-home, source-archive, and guarded disposable-VM gates are complete for
the documented macOS 26+ support range. Earlier macOS releases remain
unsupported until equivalent real-VM smoke coverage is available. Git author
identity, remote history, push, public CI, and repository settings are verified
as publication operations after this pre-commit report.

Developer ID signing and notarization remain disabled future work.
