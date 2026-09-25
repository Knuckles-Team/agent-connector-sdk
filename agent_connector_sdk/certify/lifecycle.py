"""Verify an AU connector lifecycle record without executing a connector.

This is a read-only admission check. A pin-only MCP report cannot satisfy it.
The caller supplies its trusted release keys; the record never establishes trust
in its own signing key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

__all__ = ["verify_lifecycle_record"]

_CHECKS = frozenset(
    {
        "bundle_integrity",
        "live_tool_schema",
        "fixture_ingest",
        "update",
        "delete",
        "replay_idempotency",
        "governance_preservation",
        "semantic_validation",
        "count_reconciliation",
        "cleanup",
    }
)
_FIELDS = frozenset(
    {
        "api_version",
        "kind",
        "schema_version",
        "connector",
        "certified_at",
        "mode",
        "status",
        "live_certified",
        "bundle",
        "scope",
        "checks",
        "counts",
        "semantic_validator",
        "evidence",
        "failure_class",
        "runtime_configuration",
        "signer",
        "signature_algorithm",
        "signing_public_key",
        "signature",
    }
)
_BUNDLE = frozenset(
    {"manifest_sha256", "fixtures_sha256", "shapes_sha256", "schema_version"}
)
_SCOPE = frozenset(
    {
        "sync_presets",
        "fixtures_declared",
        "fixtures_exercised",
        "tenant_bound",
        "retention_bound",
    }
)
_COUNTS = frozenset(
    {
        "initial",
        "after_ingest",
        "after_replay",
        "after_update",
        "after_delete",
        "after_delete_replay",
        "after_cleanup",
    }
)
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_CONNECTOR = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")


def _digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _bounded_count(value: Any, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _choice(value: Any, allowed: frozenset[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _signed_payload(record: Mapping[str, Any]) -> bytes:
    document = dict(record)
    document["signature"] = None
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")


def _decode_key(value: str, size: int) -> bytes:
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if (
        len(decoded) != size
        or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value
    ):
        raise ValueError("invalid canonical base64url")
    return decoded


def _valid_signature(
    record: Mapping[str, Any], trusted_public_keys: Sequence[str]
) -> bool:
    key = record.get("signing_public_key")
    signature = record.get("signature")
    signer = record.get("signer")
    if (
        not isinstance(key, str)
        or key not in trusted_public_keys
        or not isinstance(signature, str)
        or signer != "ontology-manifest-generator"
        or record.get("signature_algorithm") != "ed25519"
    ):
        return False
    try:
        digest = hashlib.sha256(_signed_payload(record)).hexdigest()
        Ed25519PublicKey.from_public_bytes(_decode_key(key, 32)).verify(
            _decode_key(signature, 64), f"{signer}:{digest}".encode("ascii")
        )
    except (ValueError, TypeError, OverflowError, InvalidSignature):
        return False
    return True


def _valid_identity(record: Mapping[str, Any]) -> bool:
    return (
        record["api_version"] == "graphos.io/v1"
        and record["kind"] == "ConnectorLiveCertification"
        and record["schema_version"] == "1"
        and isinstance(record["connector"], str)
        and _CONNECTOR.fullmatch(record["connector"]) is not None
    )


def _valid_timestamp(value: Any) -> bool:
    try:
        timestamp = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return False
    return timestamp.year >= 2020


def _valid_bundle(bundle: Any) -> bool:
    return (
        isinstance(bundle, dict)
        and set(bundle) == _BUNDLE
        and all(_digest(bundle[name]) for name in _BUNDLE - {"schema_version"})
        and isinstance(bundle["schema_version"], str)
        and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", bundle["schema_version"]) is not None
    )


def _valid_scope(scope: Any) -> bool:
    return (
        isinstance(scope, dict)
        and set(scope) == _SCOPE
        and all(
            _bounded_count(scope[name], 256)
            for name in _SCOPE - {"tenant_bound", "retention_bound"}
        )
        and scope["tenant_bound"] is True
        and scope["retention_bound"] is True
    )


def _valid_checks(checks: Any) -> bool:
    return (
        isinstance(checks, dict)
        and set(checks) == _CHECKS
        and all(
            _choice(value, frozenset({"passed", "failed", "not-run"}))
            for value in checks.values()
        )
    )


def _valid_evidence(evidence: Any) -> bool:
    return (
        isinstance(evidence, dict)
        and set(evidence) == _CHECKS
        and all(_digest(value) for value in evidence.values())
    )


def _valid_counts(counts: Any) -> bool:
    return (
        isinstance(counts, dict)
        and set(counts) <= _COUNTS
        and all(_bounded_count(value, 1_000_000) for value in counts.values())
    )


def _valid_markers(record: Mapping[str, Any]) -> bool:
    failure = record["failure_class"]
    return _choice(
        record["semantic_validator"],
        frozenset({"not-run", "declared-shacl-contract", "epistemic-graph"}),
    ) and (
        failure is None
        or (
            isinstance(failure, str)
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", failure) is not None
        )
    )


def _valid_live_outcome(record: Mapping[str, Any]) -> bool:
    checks = record["checks"]
    return (
        record["mode"] == "external-live"
        and record["status"] == "certified"
        and record["live_certified"] is True
        and record["runtime_configuration"] == "externalized"
        and record["failure_class"] is None
        and isinstance(checks, dict)
        and all(checks.get(name) == "passed" for name in _CHECKS)
    )


def _valid_general_outcome(record: Mapping[str, Any]) -> bool:
    return (
        _choice(record["mode"], frozenset({"external-live", "offline-fixture"}))
        and _choice(
            record["status"], frozenset({"certified", "offline-validated", "failed"})
        )
        and _choice(
            record["runtime_configuration"], frozenset({"none", "externalized"})
        )
        and type(record["live_certified"]) is bool
    )


def verify_lifecycle_record(
    record: Mapping[str, Any],
    *,
    trusted_public_keys: Sequence[str],
    require_live: bool = True,
) -> tuple[str, ...]:
    """Return violations for an AU aggregate lifecycle record.

    Offline fixture runs cannot satisfy the default external live admission.
    A signature attests to the checks; it cannot prove driver honesty.
    """
    if set(record) != _FIELDS:
        return ("lifecycle record fields are not exact",)
    checks = (
        (_valid_identity(record), "lifecycle identity is invalid"),
        (_valid_timestamp(record["certified_at"]), "lifecycle timestamp is invalid"),
        (_valid_bundle(record["bundle"]), "lifecycle bundle binding is invalid"),
        (_valid_scope(record["scope"]), "lifecycle scope is invalid"),
        (_valid_checks(record["checks"]), "lifecycle checks are invalid"),
        (_valid_evidence(record["evidence"]), "lifecycle evidence is invalid"),
        (_valid_counts(record["counts"]), "lifecycle counts are invalid"),
        (_valid_markers(record), "lifecycle markers are invalid"),
        (
            _valid_live_outcome(record)
            if require_live
            else _valid_general_outcome(record),
            "connector has no passing external live certification"
            if require_live
            else "lifecycle outcome is invalid",
        ),
        (
            _valid_signature(record, trusted_public_keys),
            "lifecycle release signature is invalid",
        ),
    )
    return tuple(message for valid, message in checks if not valid)
