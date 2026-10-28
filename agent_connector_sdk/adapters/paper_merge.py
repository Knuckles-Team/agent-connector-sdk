"""Deterministically merge provider metadata by explicit paper identity.

No provider call, quota decision, or document retrieval occurs here.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from agent_connector_sdk.adapters.paper_identity import _groups, _identity_tokens
from agent_connector_sdk.adapters.paper_models import (
    DocumentOffer,
    FieldAlternative,
    FieldEvidence,
    PaperQuery,
    PaperRecord,
)
from agent_connector_sdk.adapters.paper_provider import ProviderPaper

__all__ = ["merge_paper_records"]


def _json_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return value


def _field(
    group: list[ProviderPaper], field: str
) -> tuple[Any, tuple[FieldEvidence, ...], tuple[FieldAlternative, ...]]:
    values: dict[str, tuple[Any, list[FieldEvidence]]] = {}
    provider_values: dict[str, str] = {}
    for record in group:
        value = getattr(record, field)
        if value in (None, "", ()):
            continue
        encoded = json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        prior = provider_values.setdefault(record.reference.provider_id, encoded)
        if prior != encoded:
            raise ValueError("provider has conflicting field values")
        if encoded not in values:
            values[encoded] = (value, [])
        sources = values[encoded][1]
        for evidence in record.field_provenance[field]:
            if evidence not in sources:
                sources.append(evidence)
    if not values:
        return None, (), ()
    preferred, *others = values.values()
    alternatives = tuple(
        FieldAlternative(value=_json_value(value), evidence=tuple(sources))
        for value, sources in others
    )
    return preferred[0], tuple(preferred[1]), alternatives


def _canonical(group: list[ProviderPaper]) -> str:
    tokens = {token for item in group for token in _identity_tokens(item)}
    for prefix in ("doi:", "alias:", "provider:"):
        matches = sorted(token for token in tokens if token.startswith(prefix))
        if matches:
            return matches[0]
    raise ValueError("paper has no identity")


def _merge_group(group: list[ProviderPaper]) -> PaperRecord:
    fields = {
        name: _field(group, name)
        for name in ("title", "authors", "abstract", "publication_date")
    }
    references = tuple(dict.fromkeys(record.reference for record in group))
    offers = _public_offers(group)
    return PaperRecord(
        canonical_id=_canonical(group),
        revision=group[0].revision,
        title=fields["title"][0],
        authors=fields["authors"][0] or (),
        abstract=fields["abstract"][0],
        publication_date=fields["publication_date"][0],
        document_offers=offers,
        references=references,
        field_provenance={
            name: result[1] for name, result in fields.items() if result[1]
        },
        alternate_values={
            name: result[2] for name, result in fields.items() if result[2]
        },
    )


def _public_offers(group: list[ProviderPaper]) -> tuple[DocumentOffer, ...]:
    return tuple(
        dict.fromkeys(
            offer
            for record in group
            for offer in record.document_offers
            if not urlsplit(offer.url).query and not urlsplit(offer.url).fragment
        )
    )


def merge_paper_records(
    query: PaperQuery, records: tuple[ProviderPaper, ...]
) -> tuple[PaperRecord, ...]:
    """Merge one bounded batch in declared provider order.

    Unnamed providers, excessive pages, and conflicting duplicate provider IDs
    refuse before any output. Missing revisions never merge with known ones.
    """
    if len(records) > 10_000:
        raise ValueError("paper merge batch exceeds 10000 records")
    rank = {provider: index for index, provider in enumerate(query.provider_ids)}
    unique: dict[tuple[str, str, str | None], ProviderPaper] = {}
    counts = {provider: 0 for provider in query.provider_ids}
    for record in records:
        provider = record.reference.provider_id
        if provider not in rank:
            raise ValueError("paper names an undeclared provider")
        counts[provider] += 1
        if counts[provider] > query.page_bound:
            raise ValueError("provider page exceeds query bound")
        key = (provider, record.reference.record_id, record.revision)
        if key in unique and unique[key] != record:
            raise ValueError("provider identity has conflicting records")
        unique[key] = record
    ordered = tuple(
        sorted(
            unique.values(),
            key=lambda record: (
                rank[record.reference.provider_id],
                record.reference.record_id,
                record.revision or "",
            ),
        )
    )
    merged = tuple(_merge_group(group) for group in _groups(ordered))
    return tuple(
        sorted(merged, key=lambda record: (record.canonical_id, record.revision or ""))
    )
