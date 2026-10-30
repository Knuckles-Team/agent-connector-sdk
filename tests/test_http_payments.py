"""Typed 402 payment models and budget decisions."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_connector_sdk.http.payments import (
    PaymentBudget,
    PaymentChallenge,
    PaymentDecision,
    PaymentGate,
    PaymentRecord,
)


def _challenge(amount: str = "1.00") -> PaymentChallenge:
    return PaymentChallenge(
        amount=Decimal(amount),
        currency="USDC",
        payee="0xpayee",
        request_url="https://api.example/data",
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R049.1")
def test_models_are_frozen_and_typed() -> None:
    challenge = _challenge()
    with pytest.raises(ValidationError):
        challenge.amount = Decimal(2)  # type: ignore[misc]
    with pytest.raises(ValidationError):
        PaymentChallenge(amount=Decimal(0), currency="USDC", payee="p", request_url="u")
    with pytest.raises(ValidationError):
        PaymentBudget(per_call_limit=Decimal(-1))
    with pytest.raises(ValidationError):
        PaymentBudget(extra=1)  # type: ignore[call-arg]
    record = PaymentRecord(
        transaction_id="t1",
        amount=Decimal(1),
        currency="USDC",
        payee="p",
        request_url="u",
        approver="alice",
        outcome="paid",
    )
    assert set(type(record).model_fields) == {
        "transaction_id",
        "amount",
        "currency",
        "payee",
        "request_url",
        "approver",
        "outcome",
    }
    with pytest.raises(ValidationError):
        record.outcome = "x"  # type: ignore[misc]


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R049.2")
def test_decide_applies_named_limits() -> None:
    gate = PaymentGate()
    assert gate.decide(_challenge(), PaymentBudget()).allowed is False
    budget = PaymentBudget(
        per_call_limit=Decimal(5), per_day_limit=Decimal(8), spent_today=Decimal(0)
    )
    assert gate.decide(_challenge("5"), budget).allowed is True
    over_call = gate.decide(_challenge("5.01"), budget)
    assert (over_call.allowed, over_call.limit) == (False, "per_call")
    used = budget.model_copy(update={"spent_today": Decimal(4)})
    over_day = gate.decide(_challenge("5"), used)
    assert (over_day.allowed, over_day.limit) == (False, "per_day")
    assert gate.decide(_challenge("4"), used) == PaymentDecision(
        allowed=True, limit="per_day"
    )
