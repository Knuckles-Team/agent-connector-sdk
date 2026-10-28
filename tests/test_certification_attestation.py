"""Certification attestation wire shape, without producer authority claims."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_connector_sdk.certify.attestation import (
    AttestationConsumerBinding,
    CertificationAttestation,
)


def _decision(**updates: object) -> CertificationAttestation:
    fields = {
        "decision_request_digest": "a" * 64,
        "outcome": "accepted",
        "decision_timestamp": datetime(2026, 10, 27, tzinfo=UTC),
        "decision_reference": "decision-1",
        "au_consumer_binding": AttestationConsumerBinding(
            actor="actor-1", tenant="tenant-1", operation="run"
        ),
        "decision_trace_reference": "trace-1",
    }
    fields.update(updates)
    return CertificationAttestation.model_validate(fields)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R062.1")
def test_attestation_is_immutable_and_has_closed_outcomes() -> None:
    for outcome in ("accepted", "rejected", "deferred"):
        decision = _decision(outcome=outcome)
        assert (
            CertificationAttestation.model_validate_json(decision.model_dump_json())
            == decision
        )
    with pytest.raises(ValidationError):
        _decision(outcome="pending")
    with pytest.raises(ValidationError):
        _decision().outcome = "rejected"  # type: ignore[misc]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R062.1")
def test_attestation_refuses_missing_digest_and_scope() -> None:
    for value in ("", "a" * 63, "G" * 64):
        with pytest.raises(ValidationError):
            _decision(decision_request_digest=value)
    for field in ("actor", "tenant", "operation"):
        binding = {"actor": "a", "tenant": "t", "operation": "o"}
        binding[field] = ""
        with pytest.raises(ValidationError):
            AttestationConsumerBinding.model_validate(binding)
    with pytest.raises(ValidationError):
        _decision(decision_timestamp=datetime(2026, 10, 27))
