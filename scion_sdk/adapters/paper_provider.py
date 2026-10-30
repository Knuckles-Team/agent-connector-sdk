"""One provider's source-attributed paper candidate."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from scion_sdk.adapters.paper_models import (
    DocumentOffer,
    FieldEvidence,
    Identity,
    PaperQuery,
    ProviderReference,
    _Model,
)
from scion_sdk.runner.backoff import _finite_number

__all__ = ["PaperProvider", "ProviderFailure", "ProviderPage", "ProviderPaper"]


class ProviderPaper(_Model):
    """A provider record; aliases are explicit, not inferred from title."""

    reference: ProviderReference
    doi: str | None = Field(default=None, min_length=1, max_length=2048)
    canonical_alias: Identity | None = None
    revision: Identity | None = None
    title: str | None = Field(default=None, max_length=65_536)
    authors: tuple[str, ...] = Field(default=(), max_length=1000, strict=False)
    abstract: str | None = Field(default=None, max_length=1_000_000)
    publication_date: date | None = None
    document_offers: tuple[DocumentOffer, ...] = Field(
        default=(), max_length=1000, strict=False
    )
    field_provenance: dict[str, tuple[FieldEvidence, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bind_evidence(self) -> ProviderPaper:
        fields = {"title", "authors", "abstract", "publication_date"}
        if not self.field_provenance.keys() <= fields:
            raise ValueError("unknown field provenance")
        for field in fields:
            value = getattr(self, field)
            if value and not self.field_provenance.get(field):
                raise ValueError("populated fields require source evidence")
        for evidence in self.field_provenance.values():
            _check_evidence(self.reference, evidence)
        if any(
            offer.provider_id != self.reference.provider_id
            for offer in self.document_offers
        ):
            raise ValueError("document offer names another provider")
        return self


def _check_evidence(
    reference: ProviderReference, evidence: tuple[FieldEvidence, ...]
) -> None:
    if any(
        item.provider_id != reference.provider_id
        or item.source_id != reference.record_id
        for item in evidence
    ):
        raise ValueError("field evidence does not bind provider record")


class ProviderPage(_Model):
    """One bounded provider page and an optional provider-owned cursor."""

    records: tuple[ProviderPaper, ...] = Field(
        default=(), max_length=10_000, strict=False
    )
    cursor: str | None = Field(default=None, max_length=8192)


class ProviderFailure(RuntimeError):
    """A closed provider refusal without a raw response body."""

    def __init__(
        self, reason: str, *, retry_after_seconds: float | None = None
    ) -> None:
        if reason not in {
            "provider_failed",
            "rate_limited",
            "unauthorized",
            "egress_denied",
            "deadline_exceeded",
        }:
            raise ValueError("unknown provider failure")
        if retry_after_seconds is not None and (
            reason != "rate_limited"
            or not _finite_number(retry_after_seconds)
            or retry_after_seconds < 0
        ):
            raise ValueError("invalid retry delay")
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        super().__init__(reason)


@runtime_checkable
class PaperProvider(Protocol):
    """One connector-owned search operation; no provider selection occurs here."""

    async def search(self, query: PaperQuery, cursor: str | None) -> ProviderPage:
        """Fetch one declared page under the caller's held shared quota."""
        ...
