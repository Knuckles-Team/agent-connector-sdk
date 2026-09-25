"""Bind a connector manifest to an independently trusted release decision."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from agent_connector_sdk.certify.lifecycle import verify_lifecycle_record
from agent_connector_sdk.manifest.loader import ManifestError, _read_bounded
from agent_connector_sdk.manifest.model import ConnectorManifest

__all__ = [
    "canonical_manifest_hash",
    "require_certified_manifest",
    "require_release_pinned_manifest",
]

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


def canonical_manifest_hash(document: Mapping[str, Any]) -> str:
    """Hash the complete parsed YAML, excluding only its signature.

    This is the AU ``ontology.lock`` preimage. In particular, ``sync`` and
    tool-schema pins are covered even though they produce no ontology triples.
    """
    data = dict(document)
    provenance = dict(data.get("provenance") or {})
    provenance["signature"] = None
    data["provenance"] = provenance
    payload = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manifest_document(path: Path) -> tuple[ConnectorManifest, dict[str, Any], bytes]:
    payload = _read_bounded(path)
    try:
        document = yaml.safe_load(payload)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path.name} is not valid YAML") from exc
    if not isinstance(document, dict):
        raise ManifestError(f"{path.name} must be a YAML mapping")
    try:
        manifest = ConnectorManifest.model_validate(document)
    except ValueError as exc:
        raise ManifestError(f"{path.name} does not match the manifest schema") from exc
    return manifest, document, payload


def require_release_pinned_manifest(
    path: Path, *, connector: str, expected_hash: str
) -> ConnectorManifest:
    """Admit a bundled manifest against a hash supplied by trusted release data.

    The caller must obtain ``expected_hash`` outside the writable connector
    package, for example from the release ledger's ``manifest_hash`` entry.
    """
    if not isinstance(expected_hash, str) or _DIGEST.fullmatch(expected_hash) is None:
        raise ManifestError("trusted manifest release pin is missing or malformed")
    manifest, document, _ = _manifest_document(path)
    if manifest.connector != connector:
        raise ManifestError("manifest connector differs from the requested connector")
    if canonical_manifest_hash(document) != expected_hash:
        raise ManifestError("complete manifest content differs from its release pin")
    return manifest


def require_certified_manifest(
    path: Path,
    *,
    connector: str,
    lifecycle_record: Mapping[str, Any],
    trusted_public_keys: Sequence[str],
) -> ConnectorManifest:
    """Admit exact manifest bytes from a passing signed live certification.

    This cannot certify a connector on its own; it verifies the independently
    produced ten-check lifecycle record and its manifest-byte binding.
    """
    violations = verify_lifecycle_record(
        lifecycle_record, trusted_public_keys=trusted_public_keys
    )
    if violations:
        raise ManifestError("; ".join(violations))
    manifest, _, payload = _manifest_document(path)
    if manifest.connector != connector or lifecycle_record["connector"] != connector:
        raise ManifestError("lifecycle connector differs from the requested connector")
    if manifest.schema_version != lifecycle_record["bundle"]["schema_version"]:
        raise ManifestError("lifecycle schema version differs from the manifest")
    if (
        hashlib.sha256(payload).hexdigest()
        != lifecycle_record["bundle"]["manifest_sha256"]
    ):
        raise ManifestError("manifest bytes differ from the live certification bundle")
    return manifest
