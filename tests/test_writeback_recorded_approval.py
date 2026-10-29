"""Independent graph approval must bind the durable source effect."""

import time

import pytest

from agent_connector_sdk.testing.writeback import make_writeback_fixture
from agent_connector_sdk.writeback import (
    RecordedApprovalResolver,
    write_back_approval_target,
)
from agent_connector_sdk.writeback.durable_ledger import FileWriteBackLedger
from agent_connector_sdk.writeback.errors import AuthorizationDeniedError
from agent_connector_sdk.writeback.service import GovernedWriteBack


class _GraphClient:
    def __init__(self, record):
        self.record = record
        self.calls = []

    async def _send(self, method, params, graph, *, idempotency_key=None):
        self.calls.append((method, params, graph, idempotency_key))
        return self.record


def _approval(change, now):
    return {
        "change_id": change.authorization.authorization_ref,
        "kind": "governed.write-back",
        "target": write_back_approval_target(change),
        "digest": change.change_set_digest,
        "justification": "approved fixture effect",
        "proposer": change.actor,
        "proposer_parties": ["proposer"],
        "approver": "principal:human",
        "status": "approved",
        "proposed_at_ms": now - 100,
        "proposal_expires_at_ms": now + 1000,
        "window_ms": 1000,
        "approved_until_ms": now + 1000,
    }


async def test_graph_recorded_approval_permits_exact_effect(tmp_path):
    fixture = make_writeback_fixture()
    now = time.time_ns() // 1_000_000
    ledger = FileWriteBackLedger(tmp_path)
    await ledger.create(fixture.change_set)
    client = _GraphClient(_approval(fixture.change_set, now))
    resolver = RecordedApprovalResolver(ledger, client, clock_ms=lambda: now)
    port = GovernedWriteBack(fixture.transport, resolver, fixture.audit)
    await port.apply(fixture.change_set)
    assert fixture.transport.attempts == 1
    assert client.calls[0][0] == "GovernedChange"
    assert (
        client.calls[0][1]["op"]["change_id"]
        == fixture.change_set.authorization.authorization_ref
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "governed.schema-repair"),
        ("target", "other"),
        ("digest", "0" * 64),
        ("status", "proposed"),
        ("approved_until_ms", 0),
        ("approver", None),
        ("proposer", "other"),
    ],
)
async def test_missing_or_mismatched_record_refuses_before_effect(
    tmp_path, field, value
):
    fixture = make_writeback_fixture()
    now = time.time_ns() // 1_000_000
    ledger = FileWriteBackLedger(tmp_path)
    await ledger.create(fixture.change_set)
    record = _approval(fixture.change_set, now)
    record[field] = value
    port = GovernedWriteBack(
        fixture.transport,
        RecordedApprovalResolver(ledger, _GraphClient(record), clock_ms=lambda: now),
        fixture.audit,
    )
    with pytest.raises(AuthorizationDeniedError):
        await port.apply(fixture.change_set)
    assert fixture.transport.attempts == 0


async def test_unavailable_approval_refuses_without_upstream_details(tmp_path):
    fixture = make_writeback_fixture()
    ledger = FileWriteBackLedger(tmp_path)
    await ledger.create(fixture.change_set)

    class Unavailable:
        async def _send(self, *args, **kwargs):
            raise RuntimeError("secret upstream error")

    port = GovernedWriteBack(
        fixture.transport,
        RecordedApprovalResolver(ledger, Unavailable()),
        fixture.audit,
    )
    with pytest.raises(AuthorizationDeniedError) as exc:
        await port.apply(fixture.change_set)
    assert "secret" not in str(exc.value)
    assert fixture.transport.attempts == 0


async def test_revoked_during_audit_reservation_never_applies(tmp_path):
    fixture = make_writeback_fixture()
    now = time.time_ns() // 1_000_000
    ledger = FileWriteBackLedger(tmp_path)
    await ledger.create(fixture.change_set)
    client = _GraphClient(_approval(fixture.change_set, now))

    class RevokingAudit:
        async def reserve(self, change):
            reservation = await fixture.audit.reserve(change)
            client.record["status"] = "revoked"
            return reservation

    port = GovernedWriteBack(
        fixture.transport,
        RecordedApprovalResolver(ledger, client, clock_ms=lambda: now),
        RevokingAudit(),
    )
    with pytest.raises(AuthorizationDeniedError):
        await port.apply(fixture.change_set)
    assert fixture.transport.attempts == 0


async def test_durable_connector_uses_injected_recorded_approval(tmp_path):
    from agent_connector_sdk.writeback.connector import DurableWritableConnector

    fixture = make_writeback_fixture()
    now = time.time_ns() // 1_000_000
    ledger = FileWriteBackLedger(tmp_path)
    client = _GraphClient(_approval(fixture.change_set, now))
    resolver = RecordedApprovalResolver(ledger, client, clock_ms=lambda: now)
    connector = DurableWritableConnector(
        fixture.change_set.connector_id,
        fixture.transport,
        ledger,
        audit=fixture.audit,
        authorization_verifier=resolver,
    )
    await connector.register(fixture.change_set)
    client.record["status"] = "revoked"
    with pytest.raises(AuthorizationDeniedError):
        await connector.apply(fixture.change_set)
    assert fixture.transport.attempts == 0
    client.record["status"] = "approved"
    await connector.apply(fixture.change_set)
    assert fixture.transport.attempts == 1


def test_approval_target_is_stable_and_unambiguous():
    change = make_writeback_fixture().change_set
    assert write_back_approval_target(change) == (
        "write-back:09a998fb2b7e1a15fbe3359bb3ffd466db8bb972f5e64c016e5e17f54384ff4f"
    )
    other = change.model_copy(
        update={"tenant_id": "tenant-1change", "change_set_id": "-1"}
    )
    assert write_back_approval_target(other) != write_back_approval_target(change)
