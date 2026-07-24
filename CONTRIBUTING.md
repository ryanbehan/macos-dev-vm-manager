# Contributing

Contributions are welcome for supported Apple-silicon Macs.

1. Read `README.md`, `SECURITY.md`, and the applicable files under `spec/`.
2. Keep VM bundles, IPSWs, disk images, saved states, credentials, certificates,
   local paths, personal identifiers, and generated apps out of commits.
3. Add or update tests for behavior changes.
4. Run:

   ```sh
   PYTHONPATH=src python3 -m unittest discover -s tests
   swift test --package-path runner
   shellcheck script/*.sh
   ./script/build_runner.sh --signing adhoc
   python3 script/check_release_hygiene.py --allow-author
   ```

5. Keep commits focused and use a privacy-preserving public Git author identity.

Changes to lifecycle safety, permanent deletion, migration, signing,
entitlements, Apple restore handling, or public release behavior must update the
relevant specification and explain their safety evidence.

By contributing, you agree that your contribution is licensed under the root
MIT license and that any adapted third-party material has compatible provenance
and attribution.
