"""Byte and change-set bindings for the repository effect contract."""

import base64
import hashlib

import pytest
from pydantic import ValidationError

from agent_connector_sdk.ports.writeback_transport import AuditBoundWriteBackTransport
from agent_connector_sdk.testing.writeback import make_writeback_fixture
from agent_connector_sdk.writeback import (
    RepositorySourceEffectIntent,
    RepositorySourceEffectReceipt,
    RepositorySourceEffectRequest,
)


def _intent():
    payload = b"\x00hello\n"
    return {
        "schema_version": 1,
        "repository_id": "repository-1",
        "target_ref": "refs/heads/main",
        "relative_path": "nested/file.bin",
        "base_revision": "a" * 40,
        "expected_file_digest": "b" * 64,
        "expected_executable": False,
        "action": "update",
        "payload_base64": base64.b64encode(payload).decode(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_size": len(payload),
        "executable": False,
        "adapter_contract_digest": "c" * 64,
    }


def _request():
    intent = RepositorySourceEffectIntent.model_validate(_intent())
    change = make_writeback_fixture().change_set.model_copy(
        update={
            "entity_id": intent.repository_id,
            "base_source_version": intent.base_revision,
            "desired_patch": {"repository_effect": intent.model_dump(mode="json")},
            "field_scope": ["repository_effect"],
            "field_provenance": {"repository_effect": "fixture"},
        }
    )
    change = change.model_copy(update={"change_set_digest": change.canonical_digest()})
    return RepositorySourceEffectRequest(
        schema_version=1, change_set=change, intent=intent
    )


def test_exact_bytes_and_canonical_change_set():
    request = _request()
    assert (
        RepositorySourceEffectRequest.model_validate_json(request.model_dump_json())
        == request
    )
    request.intent.require_payload_limit(7)
    with pytest.raises(ValueError):
        request.intent.require_payload_limit(6)
    with pytest.raises(ValidationError):
        RepositorySourceEffectRequest(
            schema_version=1,
            change_set=request.change_set,
            intent=request.intent.model_copy(update={"target_ref": "refs/heads/other"}),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("base_revision", "main"),
        ("payload_base64", "AGhlbGxvCg"),
        ("payload_size", True),
        ("payload_sha256", "d" * 64),
        ("relative_path", "../file"),
        ("relative_path", "a/%2e%2e/b"),
        ("relative_path", "/file"),
        ("expected_executable", None),
        ("action", "delete"),
    ],
)
def test_invalid_effect_is_refused(field, value):
    data = _intent()
    data[field] = value
    with pytest.raises(ValidationError):
        RepositorySourceEffectIntent.model_validate(data)


def test_change_set_binding_distinguishes_boolean_from_integer():
    request = _request()
    patch = {
        "repository_effect": dict(request.change_set.desired_patch["repository_effect"])
    }
    patch["repository_effect"]["executable"] = 0
    altered = request.change_set.model_copy(update={"desired_patch": patch})
    altered = altered.model_copy(
        update={"change_set_digest": altered.canonical_digest()}
    )
    with pytest.raises(ValidationError):
        RepositorySourceEffectRequest(
            schema_version=1, change_set=altered, intent=request.intent
        )


def test_receipt_digest_binds_actual_revision_and_readback():

    fields = {
        "schema_version": 1,
        "tenant_id": "tenant",
        "actor": "actor",
        "connector_id": "connector",
        "source_instance_id": "source",
        "repository_id": "repo",
        "target_ref": "refs/heads/main",
        "relative_path": "folder/file",
        "base_revision": "a" * 40,
        "change_set_id": "set",
        "change_set_digest": "b" * 64,
        "idempotency_key": "key",
        "approval_ref": "approval",
        "approval_decision_digest": "c" * 64,
        "audit_reservation_id": "audit",
        "adapter_contract_digest": "d" * 64,
        "effect_revision": "e" * 40,
        "readback_sha256": "f" * 64,
        "readback_size": 12,
        "executable": False,
    }
    receipt = RepositorySourceEffectReceipt.model_validate(fields)
    roundtrip = RepositorySourceEffectReceipt.model_validate_json(
        receipt.model_dump_json()
    )
    assert roundtrip.receipt_digest() == receipt.receipt_digest()
    assert (
        receipt.model_copy(update={"effect_revision": "1" * 40}).receipt_digest()
        != receipt.receipt_digest()
    )
    assert (
        receipt.model_copy(update={"readback_size": 13}).receipt_digest()
        != receipt.receipt_digest()
    )
    fields["effect_revision"] = "main"
    with pytest.raises(ValidationError):
        RepositorySourceEffectReceipt.model_validate(fields)


def test_wire_parser_refuses_duplicate_keys_and_over_limit():
    request = _request()
    wire = request.model_dump_json().encode()
    assert (
        RepositorySourceEffectRequest.from_wire_json(wire, max_payload_size=7)
        == request
    )
    with pytest.raises(ValueError):
        RepositorySourceEffectRequest.from_wire_json(wire, max_payload_size=6)
    duplicate = wire.replace(
        b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1
    )
    with pytest.raises(ValueError, match="duplicate"):
        RepositorySourceEffectRequest.from_wire_json(duplicate, max_payload_size=7)


async def test_verified_audit_reservation_reaches_bound_transport(monkeypatch):
    fixture = make_writeback_fixture()
    observed = []
    apply = fixture.transport.apply

    async def apply_reserved(change_set, expected_version, reservation):
        observed.append(reservation)
        return await apply(change_set, expected_version)

    monkeypatch.setattr(
        fixture.transport, "apply_reserved", apply_reserved, raising=False
    )
    assert isinstance(fixture.transport, AuditBoundWriteBackTransport)
    await fixture.port.apply(fixture.change_set)
    assert len(observed) == 1
    assert observed[0].effect_key == fixture.change_set.idempotency_key
    assert observed[0].change_set_digest == fixture.change_set.change_set_digest
    assert observed[0].reservation_id


def test_request_revalidates_unchecked_copied_intent():
    request = _request()
    invalid = request.intent.model_copy(update={"payload_size": 999})
    change = request.change_set.model_copy(
        update={"desired_patch": {"repository_effect": invalid.model_dump(mode="json")}}
    )
    change = change.model_copy(update={"change_set_digest": change.canonical_digest()})
    with pytest.raises(ValidationError):
        RepositorySourceEffectRequest(
            schema_version=1, change_set=change, intent=invalid
        )


def test_receipt_binds_approved_request_and_reservation():
    from agent_connector_sdk.ports.audit_reservation import AuditReservation

    request = _request()
    change, intent = request.change_set, request.intent
    reservation = AuditReservation(
        "audit-1", change.idempotency_key, change.change_set_digest
    )
    receipt = RepositorySourceEffectReceipt(
        schema_version=1,
        tenant_id=change.tenant_id,
        actor=change.actor,
        connector_id=change.connector_id,
        source_instance_id=change.source_instance_id,
        repository_id=intent.repository_id,
        target_ref=intent.target_ref,
        relative_path=intent.relative_path,
        base_revision=intent.base_revision,
        change_set_id=change.change_set_id,
        change_set_digest=change.change_set_digest,
        idempotency_key=change.idempotency_key,
        approval_ref=change.authorization.authorization_ref,
        approval_decision_digest=change.authorization.decision_digest,
        audit_reservation_id=reservation.reservation_id,
        adapter_contract_digest=intent.adapter_contract_digest,
        effect_revision="e" * 40,
        readback_sha256=intent.payload_sha256,
        readback_size=intent.payload_size,
        executable=intent.executable,
    )
    receipt.require_binding(request, reservation)
    with pytest.raises(ValueError, match="binding"):
        receipt.model_copy(
            update={"readback_size": intent.payload_size + 1}
        ).require_binding(request, reservation)
    with pytest.raises(ValueError, match="binding"):
        receipt.require_binding(
            request, AuditReservation("audit-1", "wrong", change.change_set_digest)
        )


async def test_audit_bound_transport_never_receives_unreserved_effect(monkeypatch):
    from agent_connector_sdk.writeback.errors import AuditReservationUnavailableError

    fixture = make_writeback_fixture()
    fixture.audit.deny_next(fixture.change_set.idempotency_key)
    called = False

    async def apply_reserved(change_set, expected_version, reservation):
        nonlocal called
        called = True
        raise AssertionError("must not reach the transport")

    monkeypatch.setattr(
        fixture.transport, "apply_reserved", apply_reserved, raising=False
    )
    with pytest.raises(AuditReservationUnavailableError):
        await fixture.port.apply(fixture.change_set)
    assert not called


def test_independent_readback_requires_exact_bytes_and_mode():
    intent = _request().intent
    intent.require_readback(b"\x00hello\n", False)
    with pytest.raises(ValueError, match="bytes"):
        intent.require_readback(b"\x00hELlo\n", False)
    with pytest.raises(ValueError, match="mode"):
        intent.require_readback(b"\x00hello\n", True)
    with pytest.raises(ValueError, match="mode"):
        intent.require_readback(b"\x00hello\n", 0)
