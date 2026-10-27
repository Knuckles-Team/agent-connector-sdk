"""D18 write-back port, reference transport and conformance contracts."""

from __future__ import annotations

import pytest
from epistemic_graph.generated.write_back import (
    WriteBackAuthorizationMode,
    WriteBackEffectStatus,
)
from pydantic import ValidationError

from agent_connector_sdk.ports.audit_reservation import AuditReservationPort
from agent_connector_sdk.ports.authorization_verifier import AuthorizationVerifier
from agent_connector_sdk.ports.writeback import WriteBackPort
from agent_connector_sdk.ports.writeback_transport import WriteBackTransport
from agent_connector_sdk.testing.results import assert_conformant
from agent_connector_sdk.testing.writeback import (
    WriteBackFixture,
    WriteBackFixtureFactory,
    make_writeback_fixture,
    run_writeback_suite,
)
from agent_connector_sdk.writeback.authorization import (
    DeterministicAuthorizationVerifier,
)
from agent_connector_sdk.writeback.errors import (
    AuthorizationDeniedError,
    ChangeSetExpiredError,
    ChangeSetValidationError,
    IdempotencyConflictError,
    OutcomeUncertainError,
    ReconciliationRequiredError,
    SourceVersionConflictError,
    WriteBackError,
)
from agent_connector_sdk.writeback.memory import (
    FixtureUncertainty,
    InMemoryWriteBackTransport,
)
from agent_connector_sdk.writeback.models import DryRunObservation, SourceSnapshot
from agent_connector_sdk.writeback.service import GovernedWriteBack
from agent_connector_sdk.writeback.validation import (
    require_authorized,
    require_base,
    require_effect,
    require_reconciliation,
)


async def test_reference_writeback_passes_the_tck() -> None:
    fixture = make_writeback_fixture()
    assert isinstance(fixture.port, WriteBackPort)
    assert_conformant(await run_writeback_suite(make_writeback_fixture))


async def test_public_writeback_contracts_are_live() -> None:
    factory: WriteBackFixtureFactory = make_writeback_fixture
    fixture = factory()
    verifier = DeterministicAuthorizationVerifier()
    verifier.grant(fixture.change_set)
    assert isinstance(fixture, WriteBackFixture)
    assert isinstance(fixture.port, GovernedWriteBack)
    assert isinstance(fixture.transport, InMemoryWriteBackTransport)
    assert isinstance(fixture.transport, WriteBackTransport)
    assert isinstance(verifier, AuthorizationVerifier)
    assert isinstance(fixture.audit, AuditReservationPort)
    current = await fixture.port.current_version(fixture.change_set)
    assert isinstance(current, SourceSnapshot)
    require_base(fixture.change_set, current)
    require_authorized(fixture.change_set, await verifier.verify(fixture.change_set))
    preview = await fixture.port.dry_run(fixture.change_set)
    assert isinstance(preview, DryRunObservation)
    applied = await fixture.port.apply(fixture.change_set)
    require_effect(fixture.change_set, applied)
    reconciled = await fixture.transport.reconcile(fixture.change_set)
    require_reconciliation(fixture.change_set, reconciled)


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004.15")
@pytest.mark.parametrize(
    "alteration",
    [
        {"source_version": "v2"},
        {"before": {"status": "wrong"}},
        {"after": {"status": "wrong"}},
        {"after": {"status": "approved", "extra": "hidden"}},
        {"changed_fields": ()},
        {"changed_fields": ("status", "status")},
        {"before": {"status": True}},
    ],
)
async def test_dry_run_rejects_mismatched_preview(
    monkeypatch: pytest.MonkeyPatch, alteration: dict[str, object]
) -> None:
    fixture = make_writeback_fixture()
    fixture.transport.seed(fixture.change_set.entity_id, "v1", {"status": 1})
    valid = await fixture.port.dry_run(fixture.change_set)
    assert valid.before == {"status": 1}
    assert valid.after == {"status": "approved"}
    preview = fixture.transport.preview

    async def forged_preview(change_set, current):
        return (await preview(change_set, current)).model_copy(update=alteration)

    monkeypatch.setattr(fixture.transport, "preview", forged_preview)
    with pytest.raises(ChangeSetValidationError, match="dry-run"):
        await fixture.port.dry_run(fixture.change_set)
    assert fixture.transport.attempts == 0


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004.15")
async def test_dry_run_rejects_snapshot_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = make_writeback_fixture()
    preview = fixture.transport.preview

    async def forged_preview(change_set, current):
        current.fields["status"] = "forged"
        return await preview(change_set, current)

    monkeypatch.setattr(fixture.transport, "preview", forged_preview)
    with pytest.raises(ChangeSetValidationError, match="dry-run"):
        await fixture.port.dry_run(fixture.change_set)
    assert fixture.transport.attempts == 0


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004.14")
async def test_uncertain_reconciliation_cannot_allow_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = make_writeback_fixture()
    fixture.transport.inject_uncertainty(
        fixture.change_set.idempotency_key, FixtureUncertainty.UNRESOLVED
    )
    attempt = await fixture.port.apply(fixture.change_set)
    assert attempt.effect_status is WriteBackEffectStatus.OUTCOME_UNCERTAIN
    reconcile = fixture.transport.reconcile

    async def invalid_reconcile(change_set):
        result = await reconcile(change_set)
        return result.model_copy(update={"retry_allowed": True})

    monkeypatch.setattr(fixture.transport, "reconcile", invalid_reconcile)
    with pytest.raises(ChangeSetValidationError, match="uncertain effect"):
        await fixture.port.reconcile(fixture.change_set)
    with pytest.raises(ReconciliationRequiredError):
        await fixture.port.apply(fixture.change_set)
    assert fixture.transport.attempts == 1


def test_public_writeback_errors_and_fixture_modes_are_typed() -> None:
    assert FixtureUncertainty.BEFORE_EFFECT.value == "before_effect"
    for error in (
        ChangeSetExpiredError,
        OutcomeUncertainError,
        ReconciliationRequiredError,
        SourceVersionConflictError,
    ):
        assert issubclass(error, WriteBackError)


@pytest.mark.parametrize(
    "mode",
    [
        WriteBackAuthorizationMode.STANDING_POLICY,
        WriteBackAuthorizationMode.MANUAL_TRIGGER,
    ],
)
async def test_authorization_mode_cannot_be_substituted(
    mode: WriteBackAuthorizationMode,
) -> None:
    fixture = make_writeback_fixture()
    authorization = fixture.change_set.authorization.model_copy(update={"mode": mode})
    changed = fixture.change_set.model_copy(
        update={"change_set_digest": "0" * 64, "authorization": authorization}
    )
    changed = changed.model_copy(
        update={"change_set_digest": changed.canonical_digest()}
    )
    with pytest.raises(AuthorizationDeniedError):
        await fixture.port.apply(changed)


async def test_unknown_authorization_mode_fails_closed() -> None:
    fixture = make_writeback_fixture()
    payload = fixture.change_set.model_dump()
    payload["authorization"]["mode"] = "caller_says_yes"
    with pytest.raises(ValidationError):
        type(fixture.change_set).model_validate(payload)


async def test_patch_cannot_escape_approved_field_scope() -> None:
    fixture = make_writeback_fixture()
    changed = fixture.change_set.model_copy(
        update={"desired_patch": {"priority": "urgent"}}
    )
    with pytest.raises(ChangeSetValidationError):
        await fixture.port.dry_run(changed)


async def test_idempotency_key_cannot_name_a_different_digest() -> None:
    fixture = make_writeback_fixture()
    result = await fixture.port.apply(fixture.change_set)
    assert result.effect_status is WriteBackEffectStatus.APPLIED
    changed = fixture.change_set.model_copy(
        update={
            "change_set_digest": "0" * 64,
            "desired_patch": {"priority": "urgent"},
            "field_scope": ["priority"],
            "field_provenance": {"priority": "fixture:priority"},
        }
    )
    changed = changed.model_copy(
        update={"change_set_digest": changed.canonical_digest()}
    )
    with pytest.raises(IdempotencyConflictError):
        await fixture.port.apply(changed)
