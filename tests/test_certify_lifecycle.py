"""AU lifecycle evidence cannot be substituted with an MCP pin report."""

from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_connector_sdk.certify.lifecycle import verify_lifecycle_record

CHECKS = (
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
)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _record() -> tuple[dict[str, object], str, Ed25519PrivateKey]:
    private = Ed25519PrivateKey.generate()
    public = _b64(
        private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    digest = "a" * 64
    record: dict[str, object] = {
        "api_version": "graphos.io/v1",
        "kind": "ConnectorLiveCertification",
        "schema_version": "1",
        "connector": "demo-agent",
        "certified_at": "2026-09-25T12:00:00Z",
        "mode": "external-live",
        "status": "certified",
        "live_certified": True,
        "bundle": {
            "manifest_sha256": digest,
            "fixtures_sha256": digest,
            "shapes_sha256": digest,
            "schema_version": "1",
        },
        "scope": {
            "sync_presets": 1,
            "fixtures_declared": 1,
            "fixtures_exercised": 1,
            "tenant_bound": True,
            "retention_bound": True,
        },
        "checks": dict.fromkeys(CHECKS, "passed"),
        "counts": {"initial": 0, "after_ingest": 1, "after_cleanup": 0},
        "semantic_validator": "epistemic-graph",
        "evidence": dict.fromkeys(CHECKS, digest),
        "failure_class": None,
        "runtime_configuration": "externalized",
        "signer": "ontology-manifest-generator",
        "signature_algorithm": "ed25519",
        "signing_public_key": public,
        "signature": None,
    }
    return record, public, private


def _sign(record: dict[str, object], private: Ed25519PrivateKey) -> None:
    record["signature"] = None
    payload = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    record["signature"] = _b64(
        private.sign(f"ontology-manifest-generator:{digest}".encode("ascii"))
    )


def test_signed_external_live_record_requires_explicit_trust() -> None:
    record, public, private = _record()
    _sign(record, private)
    assert verify_lifecycle_record(record, trusted_public_keys=(public,)) == ()
    assert "signature" in " ".join(
        verify_lifecycle_record(record, trusted_public_keys=())
    )


def test_offline_and_incomplete_checks_never_pass_live_admission() -> None:
    record, public, private = _record()
    record["mode"] = "offline-fixture"
    record["status"] = "offline-validated"
    record["live_certified"] = False
    record["runtime_configuration"] = "none"
    _sign(record, private)
    assert (
        verify_lifecycle_record(
            record, trusted_public_keys=(public,), require_live=False
        )
        == ()
    )
    assert "external live" in " ".join(
        verify_lifecycle_record(record, trusted_public_keys=(public,))
    )
    record["mode"] = "external-live"
    record["status"] = "certified"
    record["live_certified"] = True
    record["runtime_configuration"] = "externalized"
    record["checks"]["delete"] = "not-run"  # type: ignore[index]
    _sign(record, private)
    assert "external live" in " ".join(
        verify_lifecycle_record(record, trusted_public_keys=(public,))
    )


def test_tampering_extra_fields_and_pin_report_are_rejected() -> None:
    record, public, private = _record()
    _sign(record, private)
    tampered = deepcopy(record)
    tampered["counts"]["after_cleanup"] = 1  # type: ignore[index]
    assert "signature" in " ".join(
        verify_lifecycle_record(tampered, trusted_public_keys=(public,))
    )
    extra = deepcopy(record)
    extra["endpoint"] = "hidden"
    assert verify_lifecycle_record(extra, trusted_public_keys=(public,)) == (
        "lifecycle record fields are not exact",
    )
    assert verify_lifecycle_record({"passed": True}, trusted_public_keys=(public,)) == (
        "lifecycle record fields are not exact",
    )
