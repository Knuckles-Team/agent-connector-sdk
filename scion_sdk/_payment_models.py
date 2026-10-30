"""Payment protocol value types and budget limits."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _valid_amount(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and 0 <= value <= sys.float_info.max
    )


class PaymentStatus(StrEnum):
    """Lifecycle states for a payment."""

    PENDING = "pending"
    CHALLENGED = "challenged"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REJECTED_BY_GUARD = "rejected_by_guard"


@dataclass
class PaymentChallenge:
    """
    An HTTP 402 challenge received from a paywall-protected resource.
    Contains the payment requirements to unlock the resource.
    """

    resource_url: str
    amount: float
    currency: str = "USDC"
    recipient_address: str = ""
    chain: str = "base"
    challenge_id: str = ""
    expires_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentProof:
    """
    Proof of payment for inclusion in the request header.
    Submitted as 'Payment-Proof' HTTP header to unlock the resource.
    """

    challenge_id: str
    transaction_hash: str
    amount: float
    currency: str
    chain: str
    sender_address: str
    recipient_address: str
    signed_at: str = ""
    proof_hash: str = ""

    def __post_init__(self) -> None:
        if not self.signed_at:
            self.signed_at = datetime.now(UTC).isoformat()
        if not self.proof_hash:
            content = f"{self.challenge_id}:{self.transaction_hash}:{self.amount}:{self.chain}"
            self.proof_hash = hashlib.sha256(content.encode()).hexdigest()[:32]


@dataclass
class PaymentRecord:
    """Complete record of a payment transaction for KG persistence."""

    payment_id: str
    status: PaymentStatus
    challenge: PaymentChallenge
    proof: PaymentProof | None = None
    created_at: str = ""
    completed_at: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


@dataclass
class BudgetLimits:
    """Configurable budget limits for autonomous payments."""

    max_single_payment: float = 0.0
    max_daily_spend: float = 0.0
    max_monthly_spend: float = 1000.0
    allowed_currencies: list[str] = field(
        default_factory=lambda: ["USDC", "USDT", "DAI"]
    )
    allowed_chains: list[str] = field(
        default_factory=lambda: ["base", "ethereum", "solana"]
    )
    require_approval_above: float = 50.0
