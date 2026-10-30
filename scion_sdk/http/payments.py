"""Typed 402 payment models and the budget decision for the governed HTTP client.

Authorization only: nothing here sends a payment header. The X402 proof and
signing helpers stay in :mod:`scion_sdk.payments`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "PaymentBudget",
    "PaymentChallenge",
    "PaymentDecision",
    "PaymentGate",
    "PaymentRecord",
]

LimitName = Literal["per_call", "per_day"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PaymentChallenge(_Frozen):
    """An HTTP 402 payment demand."""

    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(min_length=1)
    payee: str = Field(min_length=1)
    request_url: str = Field(min_length=1)
    scheme: str = Field(default="x402", min_length=1)


class PaymentBudget(_Frozen):
    """Limits a caller grants. Both default to zero, so nothing is paid."""

    per_call_limit: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    per_day_limit: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    spent_today: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)

    @property
    def remaining_today(self) -> Decimal:
        """Day allowance left; never negative."""
        return max(self.per_day_limit - self.spent_today, Decimal(0))


class PaymentRecord(_Frozen):
    """Provenance of one payment attempt, paid or refused."""

    transaction_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(min_length=1)
    payee: str = Field(min_length=1)
    request_url: str = Field(min_length=1)
    approver: str | None = None
    outcome: str = Field(min_length=1)


class PaymentDecision(_Frozen):
    """Budget verdict. ``limit`` names the limit that decided it."""

    allowed: bool
    limit: LimitName


class PaymentGate:
    """Decides whether a challenge fits the remaining budget."""

    def decide(
        self, challenge: PaymentChallenge, budget: PaymentBudget
    ) -> PaymentDecision:
        """Allow only when both the per-call and the remaining daily limit fit."""
        if challenge.amount > budget.per_call_limit:
            return PaymentDecision(allowed=False, limit="per_call")
        if challenge.amount > budget.remaining_today:
            return PaymentDecision(allowed=False, limit="per_day")
        return PaymentDecision(allowed=True, limit="per_day")
