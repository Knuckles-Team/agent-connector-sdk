"""Typed certification decision and consumer binding.

Constructing these values checks their shape only. The producer and consumer
must authenticate the decision and enforce its tenant and actor scope.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["AttestationConsumerBinding", "CertificationAttestation"]

_IDENTIFIER = Field(min_length=1, max_length=512, pattern=r"^\S(?:.*\S)?$")
_DIGEST = Field(pattern=r"^[0-9a-f]{64}$")


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class AttestationConsumerBinding(_Strict):
    """Actor, tenant and operation whose authority must be checked by AU."""

    actor: str = _IDENTIFIER
    tenant: str = _IDENTIFIER
    operation: str = _IDENTIFIER


class CertificationAttestation(_Strict):
    """An immutable decision reference; it does not itself authorize effects."""

    decision_request_digest: str = _DIGEST
    outcome: Literal["accepted", "rejected", "deferred"]
    decision_timestamp: datetime
    decision_reference: str = _IDENTIFIER
    au_consumer_binding: AttestationConsumerBinding
    decision_trace_reference: str = _IDENTIFIER
    refusal_reason: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("decision_timestamp")
    @classmethod
    def _aware_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("decision timestamp must include a timezone")
        return value
