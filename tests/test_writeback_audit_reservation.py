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


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004.3")
@pytest.mark.parametrize("binding", ["key", "digest", "blank", "unavailable"])
async def test_bound_reservation_refuses_before_mutation(binding: str) -> None:
    from agent_connector_sdk.ports.audit_reservation import AuditReservation

    fixture = make_writeback_fixture()
    verifier = DeterministicAuthorizationVerifier()
    verifier.grant(fixture.change_set)

    class WrongReservation:
        async def reserve(self, change_set: Any) -> AuditReservation:
            assert fixture.transport.attempts == 0
            if binding == "unavailable":
                raise AuditReservationUnavailableError("unavailable")
            return AuditReservation(
                "" if binding == "blank" else "reservation",
                "other" if binding == "key" else change_set.idempotency_key,
                "other" if binding == "digest" else change_set.change_set_digest,
            )

    port = GovernedWriteBack(fixture.transport, verifier, WrongReservation())
    with pytest.raises(AuditReservationUnavailableError):
        await port.apply(fixture.change_set)
    assert fixture.transport.attempts == 0


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004.3")
async def test_file_reservation_is_reused_after_no_effect_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_connector_sdk.writeback.memory import FixtureUncertainty

    fixture = make_writeback_fixture()
    verifier = DeterministicAuthorizationVerifier()
    verifier.grant(fixture.change_set)
    audit = FileAuditReservation(tmp_path)
    port = GovernedWriteBack(fixture.transport, verifier, audit)
    original_apply = fixture.transport.apply

    async def check_reservation(*args: Any) -> Any:
        assert (tmp_path / "audit_reservation.json").is_file()
        return await original_apply(*args)

    monkeypatch.setattr(fixture.transport, "apply", check_reservation)
    fixture.transport.inject_uncertainty(
        fixture.change_set.idempotency_key, FixtureUncertainty.BEFORE_EFFECT
    )
    first_attempt = await port.apply(fixture.change_set)
    assert first_attempt.effect_status is WriteBackEffectStatus.OUTCOME_UNCERTAIN
    initial = await audit.reserve(fixture.change_set)
    assert (tmp_path / "audit_reservation.json").is_file()
    assert (
        await port.reconcile(fixture.change_set)
    ).effect_status is WriteBackEffectStatus.NO_EFFECT
    restarted = FileAuditReservation(tmp_path)
    assert await restarted.reserve(fixture.change_set) == initial
    result = await GovernedWriteBack(fixture.transport, verifier, restarted).apply(
        fixture.change_set
    )
    assert result.effect_status is WriteBackEffectStatus.APPLIED
    assert await restarted.reserve(fixture.change_set) == initial


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004.3")
async def test_file_sync_failure_prevents_source_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_connector_sdk.writeback_sinks.governed as governed

    fixture = make_writeback_fixture()
    verifier = DeterministicAuthorizationVerifier()
    verifier.grant(fixture.change_set)

    def fail_sync(_fd: int) -> None:
        raise OSError("sync unavailable")

    monkeypatch.setattr(governed.os, "fsync", fail_sync)
    port = GovernedWriteBack(
        fixture.transport, verifier, FileAuditReservation(tmp_path)
    )
    with pytest.raises(AuditReservationUnavailableError):
        await port.apply(fixture.change_set)
    assert fixture.transport.attempts == 0
    assert not (tmp_path / "audit_reservation.json").exists()


@pytest.mark.spec("SDK-GOVERNED-WRITEBACK-R004.3")
async def test_concurrent_file_reservations_share_one_binding(tmp_path: Path) -> None:
    import asyncio

    fixture = make_writeback_fixture()
    reservations = await asyncio.gather(
        *(FileAuditReservation(tmp_path).reserve(fixture.change_set) for _ in range(8))
    )
    assert all(item == reservations[0] for item in reservations)
    assert reservations[0].effect_key == fixture.change_set.idempotency_key
    assert reservations[0].change_set_digest == fixture.change_set.change_set_digest
    assert json.loads((tmp_path / "audit_reservation.json").read_text()) == {
        "reservation_id": reservations[0].reservation_id
    }
