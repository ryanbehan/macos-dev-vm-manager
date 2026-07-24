# Security Policy

## Supported versions

Security fixes are made on the latest source release. Until the first tagged
release, only the current default branch is supported.

## Reporting a vulnerability

Do not open a public issue for an unpatched vulnerability, credential, private
VM artifact, or diagnostic containing personal data. Use the repository's
private security-advisory reporting feature. Include:

- the affected version and macOS version;
- a minimal reproduction using fake or disposable VM data;
- expected and observed behavior;
- `vmctl doctor --share` output when relevant.

Never attach an IPSW, VM bundle, disk image, saved state, credential, private
key, certificate archive, or unredacted diagnostic.

The maintainers will acknowledge a valid report, coordinate remediation, and
publish an advisory when a fix is available. No response-time guarantee is made.

## Security boundaries

vmctl is a user-scoped local tool. It does not elevate privileges, alter
Keychain trust, bypass Gatekeeper, upload VM data, or provide guest isolation
beyond Apple's Virtualization framework and the host/guest configuration.
