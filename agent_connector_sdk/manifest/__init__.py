"""Connector manifest schema, sync presets, tool-schema fingerprints and loaders."""

from agent_connector_sdk.manifest.release_identity import release_identity_digest
from agent_connector_sdk.manifest.release_lock import (
    MAX_RELEASE_LOCK_BYTES,
    load_release_key_lock,
)
from agent_connector_sdk.manifest.release_signature import (
    ReleaseSignature,
    ReleaseSigningError,
    sign_release,
    verify_release,
)

__all__ = [
    "MAX_RELEASE_LOCK_BYTES",
    "ReleaseSignature",
    "ReleaseSigningError",
    "load_release_key_lock",
    "release_identity_digest",
    "sign_release",
    "verify_release",
]
