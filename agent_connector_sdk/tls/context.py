"""Build verified SSL contexts and client identities."""

from __future__ import annotations

import ssl
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from agent_connector_sdk.tls.errors import TransportSecurityError

__all__ = ["build_ssl_context", "minimum_tls_version", "unencrypted_key_pem"]

_MINIMUM_VERSIONS = {
    "TLSv1.2": ssl.TLSVersion.TLSv1_2,
    "TLSv1.3": ssl.TLSVersion.TLSv1_3,
}


def minimum_tls_version(value: object) -> ssl.TLSVersion:
    """``TLSv1.2`` (the default) or ``TLSv1.3``; anything older is rejected."""
    rendered = str(value or "TLSv1.2").strip()
    version = _MINIMUM_VERSIONS.get(rendered)
    if version is None:
        raise TransportSecurityError("tls_minimum_version_invalid")
    return version


def build_ssl_context(
    *,
    system_trust: bool,
    ca_file: Path | None,
    ca_directory: Path | None,
    minimum_version: ssl.TLSVersion,
) -> ssl.SSLContext:
    """A client context that always verifies the peer certificate and hostname."""
    context = (
        ssl.create_default_context()
        if system_trust
        else ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    )
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = minimum_version
    if ca_file is not None:
        context.load_verify_locations(cafile=str(ca_file))
    if ca_directory is not None:
        context.load_verify_locations(capath=str(ca_directory))
    return context


def unencrypted_key_pem(key_path: Path, password: str | None) -> str:
    """The client key as unencrypted PKCS#8 PEM, for clients that take no password."""
    raw = key_path.read_bytes()
    if password is None:
        return raw.decode("ascii")
    key = serialization.load_pem_private_key(raw, password=password.encode("utf-8"))
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
