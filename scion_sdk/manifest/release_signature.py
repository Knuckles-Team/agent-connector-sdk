"""Sign and verify a live release identity against explicitly trusted keys.

This API does not load a lock, establish key rotation or admit a connector.
Callers must obtain the trusted key mapping from their release authority.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from scion_sdk.credentials.provider import CredentialProvider
from scion_sdk.credentials.references import SecretReference
from scion_sdk.manifest.release_identity import release_identity_digest

if TYPE_CHECKING:
    from rdflib import Graph

    from scion_sdk.ingest.sources import IngestSourceDeclaration

__all__ = ["ReleaseSignature", "ReleaseSigningError", "sign_release", "verify_release"]

_KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_B64URL = re.compile(r"[A-Za-z0-9_-]+\Z")


class ReleaseSigningError(ValueError):
    """Release signing material or its authority is invalid."""


@dataclass(frozen=True)
class ReleaseSignature:
    """Public evidence binding a key ID to a declaration and ontology digest."""

    key_id: str
    digest: str
    signature: str


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str, length: int) -> bytes:
    if (
        not isinstance(value, str)
        or len(value) != (length * 4 + 2) // 3
        or not _B64URL.fullmatch(value)
    ):
        raise ReleaseSigningError("invalid signing material")
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise ReleaseSigningError("invalid signing material") from exc
    if len(raw) != length or _encode(raw) != value:
        raise ReleaseSigningError("invalid signing material")
    return raw


def _message(key_id: str, digest: str) -> bytes:
    if not _KEY_ID.fullmatch(key_id) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ReleaseSigningError("invalid release identity")
    return (
        b"scion-release-signature-v1\0"
        + key_id.encode("ascii")
        + b"\0"
        + digest.encode("ascii")
    )


def sign_release(
    declaration: IngestSourceDeclaration,
    graph: Graph,
    *,
    key_id: str,
    key_reference: SecretReference,
    provider: CredentialProvider,
    trusted_keys: Mapping[str, bytes],
) -> ReleaseSignature:
    """Sign only with a versioned scoped secret matching an explicitly trusted key."""
    if key_reference.scheme != "openbao" or key_reference.version is None:
        raise ReleaseSigningError(
            "release signing requires a versioned OpenBao reference"
        )
    digest = release_identity_digest(declaration, graph)
    message = _message(key_id, digest)
    seed = _decode(provider.get_secret(key_reference), 32)
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    if trusted_keys.get(key_id) != public_key:
        raise ReleaseSigningError("release signing key is not trusted")
    return ReleaseSignature(key_id, digest, _encode(private_key.sign(message)))


def verify_release(
    declaration: IngestSourceDeclaration,
    graph: Graph,
    evidence: ReleaseSignature,
    *,
    trusted_keys: Mapping[str, bytes],
) -> bool:
    """Check both current inputs and the signature against the caller's trust set."""
    if not isinstance(evidence.key_id, str) or not _KEY_ID.fullmatch(evidence.key_id):
        return False
    public_key = trusted_keys.get(evidence.key_id)
    if public_key is None:
        return False
    try:
        return _signature_valid(declaration, graph, evidence, public_key)
    except (ValueError, TypeError, InvalidSignature):
        return False


def _signature_valid(
    declaration: IngestSourceDeclaration,
    graph: Graph,
    evidence: ReleaseSignature,
    public_key: bytes,
) -> bool:
    digest = release_identity_digest(declaration, graph)
    if evidence.digest != digest:
        return False
    message = _message(evidence.key_id, digest)
    signature = _decode(evidence.signature, 64)
    Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    return True
