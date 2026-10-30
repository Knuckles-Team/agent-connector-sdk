"""Budget enforcement for autonomous payments."""

from __future__ import annotations

from collections.abc import Iterator

from scion_sdk._payment_models import BudgetLimits, PaymentChallenge, _valid_amount


class PaymentGuard:
    """
    Budget enforcement and approval workflow for autonomous payments.
    Prevents runaway spending by SI agents.
    """

    def __init__(self, limits: BudgetLimits | None = None):
        self.limits = limits or BudgetLimits()
        self._daily_spend: float = 0.0
        self._monthly_spend: float = 0.0
        self._payment_count: int = 0

    def validate(self, challenge: PaymentChallenge) -> tuple[bool, str]:
        """
        Validate a payment challenge against budget limits.

        Returns:
            (approved, reason) tuple.
        """
        reason = next(self._violations(challenge), None)
        if reason is not None:
            return False, reason
        return True, "Approved"

    def _violations(self, challenge: PaymentChallenge) -> Iterator[str]:
        """Yield the first failing budget rule's reason, in rule order."""
        limits = self.limits
        if not _valid_amount(challenge.amount) or not all(
            _valid_amount(value)
            for value in (
                limits.max_single_payment,
                limits.max_daily_spend,
                limits.max_monthly_spend,
                limits.require_approval_above,
            )
        ):
            yield "Payment amount and budget limits must be finite and non-negative"
            return
        if challenge.currency not in limits.allowed_currencies:
            yield f"Currency {challenge.currency} not in allowed list"
        if challenge.chain not in limits.allowed_chains:
            yield f"Chain {challenge.chain} not in allowed list"
        if challenge.amount > limits.max_single_payment:
            yield f"Amount {challenge.amount} exceeds single payment limit {limits.max_single_payment}"
        if self._daily_spend + challenge.amount > limits.max_daily_spend:
            yield f"Would exceed daily spend limit ({self._daily_spend + challenge.amount:.2f} > {limits.max_daily_spend})"
        if self._monthly_spend + challenge.amount > limits.max_monthly_spend:
            yield "Would exceed monthly spend limit"
        if challenge.amount > limits.require_approval_above:
            yield f"Amount {challenge.amount} requires manual approval (threshold: {limits.require_approval_above})"

    def record_spend(self, amount: float) -> None:
        """Record a completed payment for budget tracking."""
        if not _valid_amount(amount):
            raise ValueError("payment amount must be finite and non-negative")
        daily = self._daily_spend + amount
        monthly = self._monthly_spend + amount
        if not _valid_amount(daily) or not _valid_amount(monthly):
            raise ValueError("payment spend exceeds finite accounting range")
        self._daily_spend = daily
        self._monthly_spend = monthly
        self._payment_count += 1

    def reset_daily(self) -> None:
        """Reset daily spend counter (call at midnight)."""
        self._daily_spend = 0.0

    def reset_monthly(self) -> None:
        """Reset monthly spend counter (call at month start)."""
        self._monthly_spend = 0.0

    @property
    def remaining_daily(self) -> float:
        return max(0.0, self.limits.max_daily_spend - self._daily_spend)

    @property
    def remaining_monthly(self) -> float:
        return max(0.0, self.limits.max_monthly_spend - self._monthly_spend)
