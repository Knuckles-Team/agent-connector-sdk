"""Bounded paper-provider records and document evidence.

These structural models do not authenticate callers, certify providers or
turn a continuation into an authority grant.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
    model_validator,
)

__all__ = [
    "DocumentOffer",
    "DocumentReceipt",
    "FieldAlternative",
    "FieldEvidence",
    "PaperContinuation",
    "PaperQuery",
    "PaperRecord",
    "PaperSearchResult",
    "ProviderReference",
    "ProviderReport",
]

Identity = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^\S(?:.*\S)?$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Reason = Literal[
    "unauthorized",
    "unknown_provider",
    "invalid_query",
    "provider_failed",
    "rate_limited",
    "deadline_exceeded",
    "egress_denied",
    "document_unavailable",
    "unsupported_media",
    "size_exceeded",
    "integrity_failed",
    "storage_denied",
    "parse_failed",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PaperContinuation(_Model):
    """One provider cursor bound to the query and its declared provider order."""

    provider_id: Identity
    query_sha256: Digest
    provider_ids: tuple[Identity, ...] = Field(
        min_length=1, max_length=256, strict=False
    )
    schema_revision: Identity
    cursor: str = Field(min_length=1, max_length=8192)


class PaperQuery(_Model):
    """A caller-scoped query and declared execution limits."""

    tenant: Identity
    query: str = Field(min_length=1, max_length=8192)
    provider_ids: tuple[Identity, ...] = Field(default=(), max_length=256, strict=False)
    schema_revision: Identity
    continuation: Mapping[str, PaperContinuation] = Field(
        default_factory=lambda: MappingProxyType({}), max_length=256
    )
    page_bound: int = Field(default=100, ge=1, le=2**31 - 1)
    deadline_seconds: float = Field(default=60.0, gt=0, allow_inf_nan=False)

    def query_digest(self) -> str:
        """Hash the exact tenant, query, provider order and schema snapshot."""
        data = json.dumps(
            [self.tenant, self.query, self.provider_ids, self.schema_revision],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    @field_validator("continuation")
    @classmethod
    def freeze_continuation(
        cls, value: Mapping[str, PaperContinuation]
    ) -> Mapping[str, PaperContinuation]:
        return MappingProxyType(dict(value))

    @field_serializer("continuation")
    def serialize_continuation(
        self, value: Mapping[str, PaperContinuation]
    ) -> dict[str, PaperContinuation]:
        return dict(value)

    @model_validator(mode="after")
    def bound_continuations(self) -> PaperQuery:
        if (
            not self.query.strip()
            or not self.provider_ids
            or len(set(self.provider_ids)) != len(self.provider_ids)
        ):
            raise ValueError("query and distinct provider IDs are required")
        for provider, continuation in self.continuation.items():
            if (
                provider not in self.provider_ids
                or continuation.provider_id != provider
                or continuation.provider_ids != self.provider_ids
                or continuation.schema_revision != self.schema_revision
                or continuation.query_sha256 != self.query_digest()
            ):
                raise ValueError("continuation does not bind this query")
        return self


class ProviderReference(_Model):
    """A provider's exact identity for one paper revision."""

    provider_id: Identity
    record_id: Identity
    original_id: str | None = Field(default=None, max_length=2048)

    @field_validator("original_id")
    @classmethod
    def redact_url_secrets(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            return value
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("provider reference URL contains credentials")
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class FieldEvidence(_Model):
    """A value's provider or document origin and extraction location."""

    provider_id: Identity
    source_id: Identity
    location: Identity
    document_sha256: Digest | None = None


class FieldAlternative(_Model):
    """A conflicting field value with its original source evidence."""

    value: JsonValue
    evidence: tuple[FieldEvidence, ...] = Field(
        min_length=1, max_length=1000, strict=False
    )


class DocumentOffer(_Model):
    """A provider-advertised document; it has not been fetched."""

    provider_id: Identity
    url: str = Field(min_length=1, max_length=4096)
    media_type: Literal["application/pdf", "text/html"]

    @field_validator("url")
    @classmethod
    def safe_url_shape(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("document offer needs an HTTP URL without credentials")
        except ValueError:
            raise ValueError("invalid document URL") from None
        return value


class PaperRecord(_Model):
    """A canonical paper revision with source-attributed fields."""

    canonical_id: Identity
    revision: Identity | None = None
    title: str | None = Field(default=None, max_length=65_536)
    authors: tuple[str, ...] = Field(default=(), max_length=1000, strict=False)
    abstract: str | None = Field(default=None, max_length=1_000_000)
    publication_date: date | None = None
    document_offers: tuple[DocumentOffer, ...] = Field(
        default=(), max_length=1000, strict=False
    )
    references: tuple[ProviderReference, ...] = Field(
        min_length=1, max_length=1000, strict=False
    )
    field_provenance: dict[str, tuple[FieldEvidence, ...]] = Field(default_factory=dict)
    alternate_values: dict[str, tuple[FieldAlternative, ...]] = Field(
        default_factory=dict
    )


class ProviderReport(_Model):
    """One provider's outcome and next cursor without raw error bodies."""

    provider_id: Identity
    outcome: Literal["ok", "failed", "rate_limited", "refused"]
    reason: Reason | None = None
    continuation: PaperContinuation | None = None
    retry_after_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent_outcome(self) -> ProviderReport:
        if (self.outcome == "ok") != (self.reason is None):
            raise ValueError("provider outcome and reason disagree")
        if (self.outcome == "rate_limited") != (self.reason == "rate_limited"):
            raise ValueError("rate limit outcome and reason disagree")
        if self.retry_after_seconds is not None and self.outcome != "rate_limited":
            raise ValueError("retry delay needs a rate limit")
        if self.outcome != "ok" and self.continuation is not None:
            raise ValueError("failed provider cannot advance continuation")
        if (
            self.continuation is not None
            and self.continuation.provider_id != self.provider_id
        ):
            raise ValueError("continuation names another provider")
        return self


class PaperSearchResult(_Model):
    """Search results and independent provider outcomes."""

    records: tuple[PaperRecord, ...] = Field(
        default=(), max_length=100_000, strict=False
    )
    reports: tuple[ProviderReport, ...] = Field(
        min_length=1, max_length=256, strict=False
    )
    completeness: Literal["complete", "partial", "failed"]

    @model_validator(mode="after")
    def coherent_reports(self) -> PaperSearchResult:
        names = [report.provider_id for report in self.reports]
        if len(set(names)) != len(names):
            raise ValueError("duplicate provider report")
        successes = sum(report.outcome == "ok" for report in self.reports)
        expected = (
            "failed"
            if successes == 0
            else "complete"
            if successes == len(self.reports)
            else "partial"
        )
        if self.completeness != expected or (not successes and self.records):
            raise ValueError("completeness does not match provider outcomes")
        return self


class DocumentReceipt(_Model):
    """A complete tenant-scoped document and its digest-derived artifact."""

    tenant: Identity
    paper_id: Identity
    revision: Identity | None = None
    source_url: str = Field(min_length=1, max_length=4096)
    media_type: Literal["application/pdf", "text/html"]
    byte_count: int = Field(ge=1, le=2**63 - 1)
    sha256: Digest
    artifact_ref: Identity

    @field_validator("source_url")
    @classmethod
    def source_url_shape(cls, value: str) -> str:
        value = DocumentOffer.safe_url_shape(value)
        parsed = urlsplit(value)
        if parsed.query or parsed.fragment:
            raise ValueError("receipt URL must omit query and fragment")
        return value

    @field_validator("artifact_ref")
    @classmethod
    def relative_artifact(cls, value: str) -> str:
        if value.startswith("/") or any(
            part in {"", ".", ".."} for part in value.split("/")
        ):
            raise ValueError("artifact reference must be relative")
        return value
