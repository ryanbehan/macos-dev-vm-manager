# Release procedure

This project publishes source releases first. Do not attach an app bundle, IPSW,
VM bundle, disk, saved state, SDK, framework, credential, certificate, cache, or
local configuration.

## Candidate checks

1. Confirm `VERSION` and `CHANGELOG.md`.
2. Use a reviewed GitHub noreply commit author identity.
3. Run:

   ```sh
   shellcheck script/*.sh
   PYTHONPATH=src python3 -m unittest discover -s tests
   swift test --package-path runner
   ./script/build_runner.sh --signing adhoc
   python3 script/verify_app.py app/VMRunner.app
   python3 script/check_release_hygiene.py
   python3 script/prepare_source_release.py
   python3 script/check_release_hygiene.py \
     --archive dist/vmctl-$(tr -d '[:space:]' < VERSION)-source.tar.gz
   ```

4. Repeat source installation under a clean temporary or disposable macOS user
   account and complete the documented import/first-run flow with disposable VM
   data.
5. Review the candidate commit range, archive member list, checksum, and release
   notes.

## GitHub controls

Before the first push, confirm the intended public remote and review any existing
history. Require CI on the default branch, protect the release tag process, and
enable dependency alerts, secret scanning, and push protection when available.

The tag workflow uploads a scanned source-release candidate as an Actions
artifact. It does not publish a GitHub Release. Publication remains a separate
maintainer decision after clean-machine validation.

## Signing channels

The source channel uses an ad hoc signature solely to embed and verify the
virtualization entitlement. It is not a notarized public binary.

Developer ID signing, notarization, stapling, and prebuilt distribution are
future protected-release work. They require separately approved credentials and
must never run for an untrusted pull request.
