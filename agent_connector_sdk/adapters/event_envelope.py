"""The operational event envelope (SDK-OBSERVABILITY-FEEDS-R001).

RUM, security-audit and CI/CD events carry one standard envelope before they
are mapped into a generated ``SourceRecord``: stable identity, a three-point
time basis, actor/target references, a privacy label, retention metadata and
a payload digest. Validating the envelope does not interpret the event as a
verified incident, vulnerability, release, or user outcome; that conclusion
belongs to graph-side policy and analysis.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

__all__ = [
    "EventEnvelope",
    "FeedKind",
    "VisibilityLabel",
    "compute_payload_digest",
]


class FeedKind(StrEnum):
    """The three operational feed kinds SDK-OBSERVABILITY-FEEDS-R001 admits."""

    RUM = "rum"
    SECURITY_AUDIT = "security_audit"
    CI_CD = "ci_cd"


class VisibilityLabel(StrEnum):
    """The sensitivity label every event envelope must carry."""

    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    SENSITIVE = "sensitive"


def compute_payload_digest(payload: Mapping[str, JsonValue]) -> str:
    """The SDK-owned sha256 of an event payload's canonical JSON encoding.

    The digest is always computed here, never trusted from the provider: it
    is what makes a repeated event id with an unchanged payload idempotent
    and a repeated id with a changed payload a detectable conflict.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EventEnvelope(BaseModel):
    """The standard shape every operational event carries into the pipeline.

    Missing required identity or an impossible time order fails construction
    instead of being patched with the current time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    stream: str = Field(min_length=1)
    feed_kind: FeedKind
    event_kind: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    provider_event_id: str | None = None
    canonical_source_digest: str | None = None
    event_time: AwareDatetime
    source_observed_time: AwareDatetime
    ingest_time: AwareDatetime
    actor_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    trace_id: str | None = None
    visibility_label: VisibilityLabel
    license: str | None = None
    retention_expires_at: AwareDatetime | None = None
    payload: dict[str, JsonValue]
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def identity(self) -> str:
        """The event's stable identity: its provider id, or its canonical digest."""
        return self.provider_event_id or self.canonical_source_digest or ""

    @model_validator(mode="after")
    def _check_identity_and_time_basis(self) -> EventEnvelope:
        if not (self.provider_event_id or self.canonical_source_digest):
            raise ValueError(
                "event envelope needs a provider_event_id or canonical_source_digest"
            )
        if self.event_time > self.source_observed_time:
            raise ValueError("event_time is after source_observed_time")
        if self.source_observed_time > self.ingest_time:
            raise ValueError("source_observed_time is after ingest_time")
        if self.payload_digest != compute_payload_digest(self.payload):
            raise ValueError("payload_digest does not match its payload")
        return self
