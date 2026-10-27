"""SDK-GOVERNED-WRITEBACK-R004: approval, idempotency and audit reservation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from epistemic_graph.generated.write_back import WriteBackEffectStatus

from agent_connector_sdk.testing.writeback import make_writeback_fixture
from agent_connector_sdk.testing.writeback_audit import InMemoryAuditReservation
from agent_connector_sdk.writeback.authorization import (
    DeterministicAuthorizationVerifier,
)
from agent_connector_sdk.writeback.errors import AuditReservationUnavailableError
from agent_connector_sdk.writeback.service import GovernedWriteBack
from agent_connector_sdk.writeback_sinks.governed import FileAuditReservation


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004")
async def test_apply_without_an_available_reservation_makes_no_source_call() -> None:
    fixture = make_writeback_fixture()
    fixture.audit.deny_next(fixture.change_set.idempotency_key)

    try:
        await fixture.port.apply(fixture.change_set)
    except AuditReservationUnavailableError:
        pass
    else:
        raise AssertionError("apply must refuse without an audit reservation")
    assert fixture.transport.attempts == 0


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004")
async def test_replayed_apply_returns_the_identical_effect_and_key() -> None:
    fixture = make_writeback_fixture()

    first = await fixture.port.apply(fixture.change_set)
    second = await fixture.port.apply(fixture.change_set)

    assert first == second
    assert first.idempotency_key == fixture.change_set.idempotency_key
    assert first.effect_status is WriteBackEffectStatus.APPLIED
    assert fixture.transport.attempts == 1


async def test_reservation_for_the_same_key_is_reused_not_taken_twice() -> None:
    audit = InMemoryAuditReservation()
    fixture = make_writeback_fixture()

    first = await audit.reserve(fixture.change_set)
    second = await audit.reserve(fixture.change_set)

    assert first == second


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004.13")
@pytest.mark.parametrize("reservation_id", [None, "", "  ", 7])
async def test_invalid_reservation_never_applies(reservation_id: Any) -> None:
    fixture = make_writeback_fixture()
    verifier = DeterministicAuthorizationVerifier()
    verifier.grant(fixture.change_set)

    class InvalidReservation:
        async def reserve(self, change_set: Any) -> Any:
            assert fixture.transport.attempts == 0
            return reservation_id

    port = GovernedWriteBack(fixture.transport, verifier, InvalidReservation())
    with pytest.raises(AuditReservationUnavailableError):
        await port.apply(fixture.change_set)
    assert fixture.transport.attempts == 0


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004.13")
async def test_file_reservation_refuses_a_different_change_set(tmp_path: Path) -> None:
    fixture = make_writeback_fixture()
    verifier = DeterministicAuthorizationVerifier()
    verifier.grant(fixture.change_set)
    audit = FileAuditReservation(tmp_path)
    reservation_id = await audit.reserve(fixture.change_set)
    assert await audit.reserve(fixture.change_set) == reservation_id
    (tmp_path / "audit_reservation.json").write_text(
        json.dumps({"reservation_id": "audit:another:change"})
    )

    port = GovernedWriteBack(fixture.transport, verifier, audit)
    with pytest.raises(AuditReservationUnavailableError, match="binding mismatch"):
        await port.apply(fixture.change_set)
    assert fixture.transport.attempts == 0
