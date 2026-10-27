"""HTTP 402 payments: challenge parsing, budget guard, proofs and spend tracking."""

from __future__ import annotations

import pytest

from agent_connector_sdk.payments import (
    BudgetLimits,
    PaymentChallenge,
    PaymentGuard,
    PaymentProof,
    PaymentRecord,
    PaymentStatus,
    X402PaymentClient,
)


def _proof(**overrides: object) -> PaymentProof:
    fields = dict(
        challenge_id="ch:001",
        transaction_hash="0xabc",
        amount=1.0,
        currency="USDC",
        chain="base",
        sender_address="s",
        recipient_address="r",
    )
    fields.update(overrides)
    return PaymentProof(**fields)  # type: ignore[arg-type]


def test_proof_hash_is_deterministic_and_content_bound() -> None:
    assert len(_proof().proof_hash) == 32
    assert _proof().proof_hash == _proof().proof_hash
    assert _proof().proof_hash != _proof(transaction_hash="0xdef").proof_hash


# spec: SDK-FINANCE-SOURCES-R900.4
@pytest.mark.parametrize(
    ("limits", "spent", "challenge", "reason"),
    [
        (BudgetLimits(), 0.0, PaymentChallenge(resource_url="r", amount=5.0), ""),
        (
            BudgetLimits(max_single_payment=1.0),
            0.0,
            PaymentChallenge(resource_url="r", amount=5.0),
            "single payment limit",
        ),
        (
            BudgetLimits(max_daily_spend=10.0),
            8.0,
            PaymentChallenge(resource_url="r", amount=5.0),
            "daily",
        ),
        (
            BudgetLimits(allowed_currencies=["USDC"]),
            0.0,
            PaymentChallenge(resource_url="r", amount=1.0, currency="BTC"),
            "Currency",
        ),
        (
            BudgetLimits(allowed_chains=["base"]),
            0.0,
            PaymentChallenge(resource_url="r", amount=1.0, chain="polygon"),
            "hain",
        ),
        (
            BudgetLimits(require_approval_above=5.0, max_single_payment=100.0),
            0.0,
            PaymentChallenge(resource_url="r", amount=10.0),
            "manual approval",
        ),
    ],
)
def test_guard_approves_only_within_every_limit(
    limits: BudgetLimits, spent: float, challenge: PaymentChallenge, reason: str
) -> None:
    guard = PaymentGuard(limits)
    guard.record_spend(spent)
    approved, why = guard.validate(challenge)
    assert approved is (reason == "")
    assert reason.lower() in why.lower()


def test_guard_remaining_budget_and_daily_reset() -> None:
    guard = PaymentGuard(BudgetLimits(max_daily_spend=100.0))
    guard.record_spend(30.0)
    assert guard.remaining_daily == pytest.approx(70.0)
    guard.reset_daily()
    assert guard.remaining_daily == pytest.approx(100.0)


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), -1.0, True])
def test_guard_refuses_invalid_amounts_without_changing_spend(amount: float) -> None:
    client = X402PaymentClient()
    challenge = (
        client.handle_402({"X-Payment-Amount": str(amount)}, "r")
        if not isinstance(amount, bool)
        else PaymentChallenge("r", amount)
    )
    assert client.authorize_payment(challenge)[0] is False
    with pytest.raises(ValueError):
        client.guard.record_spend(amount)
    with pytest.raises(ValueError):
        client.record_payment(challenge, _proof())
    assert client.get_payment_history() == []
    assert client.guard.remaining_daily == 100.0
    assert client.guard.remaining_monthly == 1000.0


def test_guard_refuses_invalid_limits_and_accounting_overflow() -> None:
    guard = PaymentGuard(BudgetLimits(max_daily_spend=float("nan")))
    assert guard.validate(PaymentChallenge("r", 1.0))[0] is False
    guard = PaymentGuard()
    guard.record_spend(1e308)
    with pytest.raises(ValueError, match="accounting range"):
        guard.record_spend(1e308)
    assert guard._daily_spend == 1e308
    assert guard._monthly_spend == 1e308


# spec: SDK-FINANCE-SOURCES-R900.6
def test_client_parses_402_proves_and_records_spend() -> None:
    client = X402PaymentClient(
        wallet_address="0xwallet", budget_limits=BudgetLimits(max_daily_spend=5.0)
    )
    challenge = client.handle_402(
        {
            "X-Payment-Amount": "3.0",
            "X-Payment-Currency": "USDC",
            "X-Payment-Recipient": "0xrecipient",
            "X-Payment-Chain": "base",
            "X-Payment-Challenge-Id": "ch:001",
        },
        "https://api.example.test/data",
    )
    assert (challenge.amount, challenge.chain) == (3.0, "base")
    assert client.authorize_payment(challenge)[0] is True
    proof = client.create_proof(challenge, "0xtx1")
    assert (proof.sender_address, proof.transaction_hash) == ("0xwallet", "0xtx1")
    record = client.record_payment(challenge, proof)
    assert (
        isinstance(record, PaymentRecord) and record.status is PaymentStatus.CONFIRMED
    )
    assert client.get_payment_history() == [record]
    assert client.guard.remaining_daily == pytest.approx(2.0)
    headers = client.get_proof_headers(proof)
    assert "Payment-Proof" in headers and headers["X-Payment-Chain"] == "base"
