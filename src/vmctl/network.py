"""Per-VM locally administered network identity."""

from __future__ import annotations

import secrets
from pathlib import Path

from .errors import ArtifactError


def format_mac(octets: bytes) -> str:
    return ":".join(f"{value:02x}" for value in octets)


def validate_mac(value: str) -> str:
    parts = value.strip().split(":")
    try:
        octets = bytes(int(part, 16) for part in parts)
    except (ValueError, OverflowError) as error:
        raise ArtifactError("Network MAC address is invalid.") from error
    if len(parts) != 6 or any(len(part) != 2 for part in parts) or len(octets) != 6:
        raise ArtifactError("Network MAC address is invalid.")
    if octets[0] & 0x01 or not octets[0] & 0x02:
        raise ArtifactError("Network MAC address must be locally administered unicast.")
    return format_mac(octets)


def generate_mac() -> str:
    octets = bytearray(secrets.token_bytes(6))
    octets[0] = (octets[0] | 0x02) & 0xFE
    return format_mac(bytes(octets))


def derive_mac(machine_identifier: bytes) -> str:
    if len(machine_identifier) < 6:
        raise ArtifactError("Machine identifier is too short to derive a network address.")
    octets = bytearray(machine_identifier[:6])
    octets[0] = (octets[0] | 0x02) & 0xFE
    return format_mac(bytes(octets))


def ensure_network_identity(
    bundle: Path,
    *,
    generate: bool = False,
    replace: bool = False,
) -> str:
    identity = bundle / "NetworkMACAddress"
    if identity.exists() or identity.is_symlink():
        if identity.is_symlink() or not identity.is_file():
            raise ArtifactError(f"Network identity must be a regular file: {identity}")
        if not replace:
            return validate_mac(identity.read_text(encoding="ascii"))
    value = (
        generate_mac()
        if generate or replace
        else derive_mac((bundle / "MachineIdentifier").read_bytes())
    )
    identity.write_text(value + "\n", encoding="ascii")
    identity.chmod(0o600)
    return value
