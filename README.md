# vmctl

`vmctl` is a local, source-first macOS virtual-machine manager for Apple silicon.
It wraps Apple's Virtualization framework with a small command-line interface for
starting, suspending, shutting down, snapshotting, loading, resetting, and
permanently removing VM states.

The first release builds entirely from source. It does not include macOS, an IPSW,
an installed VM, Apple SDK files, certificates, or telemetry.

## Requirements

- An Apple-silicon Mac
- macOS 26 or newer
- Python 3.10 or newer
- Apple Command Line Tools providing Swift 6 and a compatible macOS SDK
- APFS storage with enough free space for the VM

Full Xcode, an Apple Developer membership, and a signing certificate are not
required. If the command-line tools are missing, run:

```sh
xcode-select --install
```

## Install from source

```sh
git clone <PUBLIC-REPOSITORY-URL>
cd vmctl
./script/install-from-source.sh
```

The installer performs all dependency checks before its first write, runs the
test suite, builds with SwiftPM, ad hoc signs the local runner with the
virtualization entitlement, verifies it, and installs versioned program files
under `$HOME/Library/Application Support/vmctl`. It creates a stable launcher at
`$HOME/.local/bin/vmctl` but never edits shell startup files.

If `$HOME/.local/bin` is not already on `PATH`, add it using the instructions
printed by the installer. Then verify:

```sh
vmctl --version
vmctl doctor
```

Ad hoc signing is local code integrity, not Developer ID distribution trust.
The installer does not create certificates, alter Keychain trust, or bypass
Gatekeeper. An unexpected quarantine attribute fails closed; rebuild from the
reviewed source checkout.

## Initialize a VM

Review the built-in walkthrough:

```sh
vmctl init
```

Clone an existing compatible bundle (recommended):

```sh
vmctl init import /path/to/VM.bundle --mode clone
vmctl init import /path/to/VM.bundle --mode clone --yes
```

The first command prints the plan and makes no changes. The second creates a
managed APFS clone, assigns a unique network identity, creates the immutable
`initial` base snapshot, and leaves the source bundle unchanged. Shut down the
source VM before importing it. Virtualization.framework suspended state may not
restore under a newly built runner; when shutdown is impossible, review and
explicitly cold boot only the clone:

```sh
vmctl init import /path/to/VM.bundle --mode clone --discard-saved-state
vmctl init import /path/to/VM.bundle --mode clone --discard-saved-state --yes
```

The source bundle and its saved-state file remain unchanged.

To install a new VM from Apple:

```sh
vmctl init install --restore latest
vmctl init install --restore latest --yes
```

You may substitute a local compatible IPSW path. Before download or installation,
vmctl shows the Apple source, cache, destination, sparse disk allocation, and free
space. Downloads go directly from the URL supplied by Apple's framework. The
cached IPSW is removed after success unless `--keep-restore-image` is specified.
Users are responsible for complying with the applicable Apple software license.

## Daily use and snapshots

```sh
vmctl start
vmctl stop                         # suspend for fast resume
vmctl shutdown                     # clean guest shutdown
vmctl snapshot dev-ready
vmctl list
vmctl tree
vmctl load dev-ready
vmctl reset                        # fresh live clone of the base
vmctl commit new-base              # snapshot live and promote
vmctl remove obsolete              # permanent deletion
```

Snapshots are independent immutable APFS clones. Their parent relationship is
descriptive, not a storage dependency: deleting a parent does not make a child
unloadable. `load`, `revert`, and `reset` use transaction-bounded rollback and
permanently remove the displaced live copy after a successful commit. They do
not maintain a recycle bin.

APFS clone directory totals are logical. Tools such as `du` can count shared
blocks repeatedly, so the displayed total may greatly exceed physically
reclaimable storage.

## Existing installations, upgrades, and uninstall

Preview configuration adoption without moving data:

```sh
vmctl migrate plan --output /tmp/vmctl-migration.json
# For the original project-local layout:
vmctl migrate plan --legacy-root /path/to/old/checkout --output /tmp/vmctl-migration.json
```

Apply only with the exact digest printed by the plan. Migration writes portable
configuration and does not move or delete VM data.

Older `recovery/live` and `recovery/removed` directories are not a recycle bin
in current vmctl. Inventory them from the retained source checkout with
`python3 script/migrate_legacy_recovery.py --manifest /tmp/recovery.json`.
Permanent cleanup requires rerunning that utility with `--execute`, the reviewed
manifest, and its exact digest. Current load/reset/remove operations do not
create those unbounded backups.

Rerunning `install-from-source.sh` installs or reuses an immutable version and
atomically switches `current`. Default uninstall preserves all VM data:

```sh
vmctl uninstall
```

Permanent data purge is separate and requires the exact path printed by help:

```sh
vmctl uninstall --purge-data --approve-path "$HOME/Library/Application Support/vmctl/data"
```

## Diagnostics, privacy, and limitations

`vmctl doctor` is local and read-only. Use `vmctl doctor --share` for issue
reports; share mode strips terminal controls and redacts home paths, usernames,
VM paths, snapshot names, and signing identity.

vmctl has no telemetry, analytics, crash upload, remote control, or VM-data
upload. Network access occurs only for a user-requested Apple restore lookup or
download.

The initial release manages one Apple-silicon macOS VM at a time. Host-to-guest
clipboard synchronization and drag-and-drop are not implemented. Use guest
networking, SSH, or a separately configured file-sharing method.

Run `vmctl help workflows` for the complete task-oriented help system.

## Development and licensing

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
swift test --package-path runner
./script/build_runner.sh --signing adhoc
python3 script/check_release_hygiene.py --allow-author
```

Project-owned code is MIT licensed. Portions of the Swift runner are adapted
from MIT-licensed Apple sample code; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and
[`LICENSES/Apple-Sample-Code-MIT.txt`](LICENSES/Apple-Sample-Code-MIT.txt).
Apple does not sponsor or endorse this project.

See [`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md), and
[`CHANGELOG.md`](CHANGELOG.md). Maintainers should also follow
[`docs/RELEASE.md`](docs/RELEASE.md) and review
[`docs/VALIDATION.md`](docs/VALIDATION.md).
