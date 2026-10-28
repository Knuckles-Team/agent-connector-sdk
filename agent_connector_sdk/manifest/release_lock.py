"""Read explicitly trusted release keys from an ontology lock file.

The caller must obtain the lock from a trusted authority. Creating a lock
does not approve a key rotation.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Hashable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from agent_connector_sdk.manifest.release_signature import (
    _KEY_ID,
    ReleaseSigningError,
    _decode,
    _encode,
)

__all__ = ["MAX_RELEASE_LOCK_BYTES", "create_release_key_lock", "load_release_key_lock"]

MAX_RELEASE_LOCK_BYTES = 1024 * 1024


class _UniqueLoader(yaml.SafeLoader):
    """Do not silently select one of two equal YAML mapping keys."""

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Hashable, Any]:
        result: dict[Hashable, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ReleaseSigningError("release lock has invalid or duplicate keys")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_release_key_lock(path: str | Path) -> Mapping[str, bytes]:
    """Load named Ed25519 pins; missing, ambiguous or malformed locks refuse.

    Each artifact entry must name `signer` and `signing_public_key`. All entries
    for a signer must pin the same canonical unpadded base64url public key.
    """
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_RELEASE_LOCK_BYTES + 1)
        if len(raw) > MAX_RELEASE_LOCK_BYTES:
            raise ReleaseSigningError("release lock exceeds the size limit")
        loader = _UniqueLoader(raw)
        try:
            document = loader.get_single_data()
        finally:
            loader.dispose()
    except (OSError, yaml.YAMLError) as exc:
        raise ReleaseSigningError("release lock is unreadable or malformed") from exc
    if not isinstance(document, dict) or not document:
        raise ReleaseSigningError("release lock has no pinned artifacts")
    keys: dict[str, bytes] = {}
    for entry in document.values():
        if not isinstance(entry, dict):
            raise ReleaseSigningError("release lock entry is malformed")
        signer = entry.get("signer")
        if not isinstance(signer, str) or not _KEY_ID.fullmatch(signer):
            raise ReleaseSigningError("release lock signer is invalid")
        encoded_key = entry.get("signing_public_key")
        if not isinstance(encoded_key, str):
            raise ReleaseSigningError("release lock public key is invalid")
        public_key = _decode(encoded_key, 32)
        if signer in keys and keys[signer] != public_key:
            raise ReleaseSigningError("release lock has conflicting signer keys")
        keys[signer] = public_key
    return MappingProxyType(keys)


def create_release_key_lock(
    path: str | Path, artifacts: Mapping[str, tuple[str, bytes]]
) -> None:
    """Create a new pin lock without replacing existing files or authorizing rotation."""
    if not artifacts:
        raise ReleaseSigningError("release lock has no pinned artifacts")
    document: dict[str, dict[str, str]] = {}
    keys: dict[str, bytes] = {}
    for artifact, (signer, public_key) in artifacts.items():
        if not isinstance(artifact, str) or not artifact:
            raise ReleaseSigningError("release lock artifact is invalid")
        if not isinstance(signer, str) or not _KEY_ID.fullmatch(signer):
            raise ReleaseSigningError("release lock signer is invalid")
        if not isinstance(public_key, bytes) or len(public_key) != 32:
            raise ReleaseSigningError("release lock public key is invalid")
        if signer in keys and keys[signer] != public_key:
            raise ReleaseSigningError("release lock has conflicting signer keys")
        keys[signer] = public_key
        document[artifact] = {
            "signer": signer,
            "signing_public_key": _encode(public_key),
        }
    raw = yaml.safe_dump(document, sort_keys=True).encode("utf-8")
    if len(raw) > MAX_RELEASE_LOCK_BYTES:
        raise ReleaseSigningError("release lock exceeds the size limit")
    target = Path(path)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temporary = handle.name
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    except OSError as exc:
        raise ReleaseSigningError("release lock could not be created") from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
