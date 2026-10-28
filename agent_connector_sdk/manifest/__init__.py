"""Connector manifest schema, sync presets, tool-schema fingerprints and loaders."""

from agent_connector_sdk.manifest.release_identity import release_identity_digest

__all__ = ["release_identity_digest"]

from agent_connector_sdk.manifest.release_signature import (
    ReleaseSignature,
    ReleaseSigningError,
    sign_release,
    verify_release,
)

__all__ += ["ReleaseSignature", "ReleaseSigningError", "sign_release", "verify_release"]
