"""HTTP 402 payment protocol client with budget limits.

:class:`X402PaymentClient` parses a 402 payment challenge, checks it against
:class:`BudgetLimits` through :class:`PaymentGuard`, wraps a signed
transaction as a :class:`PaymentProof` and renders the proof headers. Signing
the transaction belongs to the caller's wallet.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from scion_sdk._payment_guard import PaymentGuard
from scion_sdk._payment_models import (
    BudgetLimits,
    PaymentChallenge,
    PaymentProof,
    PaymentRecord,
    PaymentStatus,
)

__all__ = [
    "BudgetLimits",
    "PaymentChallenge",
    "PaymentGuard",
    "PaymentProof",
    "PaymentRecord",
    "PaymentStatus",
    "X402PaymentClient",
]

logger = logging.getLogger(__name__)


class X402PaymentClient:
    """
    HTTP 402 challenge-response handler for autonomous SI agent payments.

    Workflow:
    1. Agent requests a resource → receives HTTP 402 with PaymentChallenge
    2. PaymentGuard validates the challenge against budget limits
    3. Agent signs the payment transaction
    4. Agent resubmits request with Payment-Proof header
    5. PaymentRecord is created in KG with full PROV-O chain
    """

    def __init__(
        self,
        wallet_address: str = "",
        budget_limits: BudgetLimits | None = None,
    ):
        self.wallet_address = wallet_address
        self.guard = PaymentGuard(budget_limits)
        self._records: list[PaymentRecord] = []
        self._payment_counter = 0

    def handle_402(
        self, response_headers: Mapping[str, str], resource_url: str
    ) -> PaymentChallenge:
        """
        Parse an HTTP 402 response into a PaymentChallenge.

        Args:
            response_headers: HTTP response headers containing payment info.
            resource_url: The URL that returned 402.
        """
        return PaymentChallenge(
            resource_url=resource_url,
            amount=float(response_headers.get("X-Payment-Amount", "0")),
            currency=response_headers.get("X-Payment-Currency", "USDC"),
            recipient_address=response_headers.get("X-Payment-Recipient", ""),
            chain=response_headers.get("X-Payment-Chain", "base"),
            challenge_id=response_headers.get("X-Payment-Challenge-Id", ""),
            expires_at=response_headers.get("X-Payment-Expires", ""),
        )

    def authorize_payment(self, challenge: PaymentChallenge) -> tuple[bool, str]:
        """Validate a payment challenge against budget guards."""
        return self.guard.validate(challenge)

    def create_proof(
        self, challenge: PaymentChallenge, transaction_hash: str
    ) -> PaymentProof:
        """
        Create a payment proof after signing a transaction.

        In production, the transaction_hash comes from the blockchain wallet.
        This method wraps the signed transaction into a PaymentProof for
        inclusion in the retry request's headers.
        """
        return PaymentProof(
            challenge_id=challenge.challenge_id,
            transaction_hash=transaction_hash,
            amount=challenge.amount,
            currency=challenge.currency,
            chain=challenge.chain,
            sender_address=self.wallet_address,
            recipient_address=challenge.recipient_address,
        )

    def _proof_matches(
        self, challenge: PaymentChallenge, proof: PaymentProof | None
    ) -> bool:
        return (
            proof is not None
            and bool(challenge.challenge_id.strip())
            and bool(proof.transaction_hash.strip())
            and proof.challenge_id == challenge.challenge_id
            and proof.amount == challenge.amount
            and proof.currency == challenge.currency
            and proof.chain == challenge.chain
            and proof.recipient_address == challenge.recipient_address
            and proof.sender_address == self.wallet_address
        )

    def record_payment(
        self,
        challenge: PaymentChallenge,
        proof: PaymentProof | None = None,
        status: PaymentStatus = PaymentStatus.CONFIRMED,
        error: str = "",
    ) -> PaymentRecord:
        """Record a payment for audit trail and KG persistence."""
        if status == PaymentStatus.CONFIRMED:
            if not self._proof_matches(challenge, proof):
                raise ValueError("confirmed payment proof does not match challenge")
            self.guard.record_spend(challenge.amount)
        self._payment_counter += 1
        record = PaymentRecord(
            payment_id=f"pay:{self._payment_counter:06d}",
            status=status,
            challenge=challenge,
            proof=proof,
            error_message=error,
        )

        self._records.append(record)
        logger.info(
            f"Payment {record.payment_id}: {status.value} — {challenge.amount} {challenge.currency}"
        )
        return record

    def get_payment_history(self) -> list[PaymentRecord]:
        """Get complete payment history."""
        return list(self._records)

    def get_proof_headers(self, proof: PaymentProof) -> dict[str, str]:
        """Generate HTTP headers for payment proof submission."""
        return {
            "Payment-Proof": proof.proof_hash,
            "X-Payment-Transaction": proof.transaction_hash,
            "X-Payment-Challenge-Id": proof.challenge_id,
            "X-Payment-Chain": proof.chain,
        }
