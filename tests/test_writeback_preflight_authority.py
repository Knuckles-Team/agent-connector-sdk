"""A denied write cannot query or reserve its source."""

import pytest

from scion_sdk.ports.writeback_transport import ReservableWriteBackTransport
from scion_sdk.testing.writeback import make_writeback_fixture
from scion_sdk.writeback.authorization import (
    DeterministicAuthorizationVerifier,
)
from scion_sdk.writeback.connector import DurableWritableConnector
from scion_sdk.writeback.durable_ledger import FileWriteBackLedger
from scion_sdk.writeback.errors import AuthorizationDeniedError
from scion_sdk.writeback.service import GovernedWriteBack


@pytest.mark.asyncio
async def test_missing_authorization_refuses_before_source_reads(monkeypatch):
    fixture = make_writeback_fixture()
    calls = []

    async def no_source(*args, **kwargs):
        calls.append("source")
        raise AssertionError("source was reached")

    monkeypatch.setattr(fixture.transport, "prior_effect", no_source)
    monkeypatch.setattr(fixture.transport, "read_current", no_source)
    monkeypatch.setattr(
        fixture.transport, "prepare_writeback", no_source, raising=False
    )
    assert isinstance(fixture.transport, ReservableWriteBackTransport)
    port = GovernedWriteBack(
        fixture.transport, DeterministicAuthorizationVerifier(), fixture.audit
    )
    with pytest.raises(AuthorizationDeniedError):
        await port.apply(fixture.change_set)
    assert not calls


@pytest.mark.asyncio
async def test_denied_durable_approval_refuses_before_source_reads(
    monkeypatch, tmp_path
):
    fixture = make_writeback_fixture()
    calls = []

    async def no_source(*args, **kwargs):
        calls.append("source")
        raise AssertionError("source was reached")

    monkeypatch.setattr(fixture.transport, "prior_effect", no_source)
    monkeypatch.setattr(fixture.transport, "read_current", no_source)
    monkeypatch.setattr(
        fixture.transport, "prepare_writeback", no_source, raising=False
    )
    change = fixture.change_set.model_copy(
        update={
            "authorization": fixture.change_set.authorization.model_copy(
                update={"authorized": False}
            )
        }
    )
    change = change.model_copy(update={"change_set_digest": change.canonical_digest()})
    ledger = FileWriteBackLedger(tmp_path / "ledger")
    writer = DurableWritableConnector(
        change.connector_id, fixture.transport, ledger, audit=fixture.audit
    )
    await writer.register(change)
    with pytest.raises(AuthorizationDeniedError):
        await writer.apply(change)
    assert not calls


@pytest.mark.asyncio
async def test_authorized_reuse_of_key_for_different_effect_still_refuses():
    from scion_sdk.writeback.errors import IdempotencyConflictError

    fixture = make_writeback_fixture()
    verifier = DeterministicAuthorizationVerifier()
    verifier.grant(fixture.change_set)
    port = GovernedWriteBack(fixture.transport, verifier, fixture.audit)
    await port.apply(fixture.change_set)
    changed = fixture.change_set.model_copy(
        update={
            "desired_patch": {"priority": "urgent"},
            "field_scope": ["priority"],
            "field_provenance": {"priority": "fixture:priority"},
        }
    )
    changed = changed.model_copy(
        update={"change_set_digest": changed.canonical_digest()}
    )
    verifier.grant(changed)
    with pytest.raises(IdempotencyConflictError):
        await port.apply(changed)


@pytest.mark.asyncio
async def test_revocation_after_reservation_stops_effect(monkeypatch):
    fixture = make_writeback_fixture()
    calls = []

    async def prepare(_change):
        calls.append("prepare")

    monkeypatch.setattr(fixture.transport, "prepare_writeback", prepare, raising=False)

    class RevokedAfterPrepare:
        def __init__(self):
            self.calls = 0

        async def verify(self, change):
            self.calls += 1
            if self.calls > 1:
                raise AuthorizationDeniedError("approval revoked")
            return change.authorization

    port = GovernedWriteBack(fixture.transport, RevokedAfterPrepare(), fixture.audit)
    with pytest.raises(AuthorizationDeniedError):
        await port.apply(fixture.change_set)
    assert calls == ["prepare"]
    assert fixture.transport.attempts == 0
