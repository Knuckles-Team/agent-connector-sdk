"""Paper contracts bind identities, continuations and deterministic evidence."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from agent_connector_sdk.adapters.paper_merge import merge_paper_records
from agent_connector_sdk.adapters.paper_models import (
    DocumentOffer,
    DocumentReceipt,
    FieldAlternative,
    FieldEvidence,
    PaperContinuation,
    PaperQuery,
    PaperRecord,
    PaperSearchResult,
    ProviderReference,
    ProviderReport,
)
from agent_connector_sdk.adapters.paper_provider import ProviderPaper


def _query(**changes):
    values = {
        "tenant": "tenant",
        "query": "source systems",
        "provider_ids": ("first", "second"),
        "schema_revision": "v1",
    }
    return PaperQuery(**(values | changes))


def _paper(provider, record, *, title="Title", doi=None, revision="v1", alias=None):
    evidence = FieldEvidence(provider_id=provider, source_id=record, location="title")
    return ProviderPaper(
        reference=ProviderReference(provider_id=provider, record_id=record),
        doi=doi,
        canonical_alias=alias,
        revision=revision,
        title=title,
        field_provenance={"title": (evidence,)},
    )


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.1")
def test_query_continuations_bind_exact_request_and_limits():
    query = _query()
    token = PaperContinuation(
        provider_id="first",
        query_sha256=query.query_digest(),
        provider_ids=query.provider_ids,
        schema_revision="v1",
        cursor="next",
    )
    resumed = _query(continuation={"first": token})
    assert PaperQuery.model_validate_json(resumed.model_dump_json()) == resumed
    with pytest.raises(ValidationError):
        _query(query="different", continuation={"first": token})
    with pytest.raises(ValidationError):
        _query(provider_ids=("first", "first"))
    with pytest.raises(ValidationError):
        _query(deadline_seconds=float("nan"))
    with pytest.raises(ValidationError):
        _query(page_bound=0)


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.1")
def test_provider_outcomes_and_document_receipts_are_explicit():
    source = FieldEvidence(provider_id="first", source_id="1", location="title")
    offer = DocumentOffer(
        provider_id="first",
        url="https://example.org/a.pdf",
        media_type="application/pdf",
    )
    paper = PaperRecord(
        canonical_id="provider:first:1",
        title="Title",
        references=(ProviderReference(provider_id="first", record_id="1"),),
        field_provenance={"title": (source,)},
        document_offers=(offer,),
        publication_date=date(2026, 1, 1),
        alternate_values={
            "title": (FieldAlternative(value="Other", evidence=(source,)),)
        },
    )
    success = ProviderReport(provider_id="first", outcome="ok")
    failed = ProviderReport(
        provider_id="second", outcome="failed", reason="provider_failed"
    )
    result = PaperSearchResult(
        records=(paper,), reports=(success, failed), completeness="partial"
    )
    assert PaperSearchResult.model_validate_json(result.model_dump_json()) == result
    assert PaperSearchResult(reports=(success,), completeness="complete").records == ()
    with pytest.raises(ValidationError):
        PaperSearchResult(records=(paper,), reports=(failed,), completeness="failed")
    with pytest.raises(ValidationError):
        ProviderReport(provider_id="first", outcome="failed")
    receipt = DocumentReceipt(
        tenant="tenant",
        paper_id="paper",
        revision="v1",
        source_url="https://example.org/a.pdf",
        media_type="application/pdf",
        byte_count=10,
        sha256="a" * 64,
        artifact_ref="sha256/aa/item",
    )
    assert receipt.byte_count == 10
    for change in (
        {"artifact_ref": "../outside"},
        {"artifact_ref": "/absolute"},
        {"source_url": "https://example.org/a?token=example"},
        {"sha256": "bad"},
    ):
        with pytest.raises(ValidationError):
            DocumentReceipt.model_validate(receipt.model_dump() | change)


def test_merge_is_order_independent_and_keeps_conflicting_sources():
    first = _paper("first", "1", title="First title", doi="https://doi.org/10.1234/AbC")
    second = _paper("second", "x", title="Second title", doi="doi:10.1234/abc")
    (merged,) = merge_paper_records(_query(), (second, first))
    assert merged == merge_paper_records(_query(), (first, second))[0]
    assert merged.canonical_id == "doi:10.1234/abc" and merged.title == "First title"
    assert merged.field_provenance["title"][0].provider_id == "first"
    assert merged.alternate_values["title"][0].value == "Second title"
    assert merged.alternate_values["title"][0].evidence[0].provider_id == "second"
    assert [reference.provider_id for reference in merged.references] == [
        "first",
        "second",
    ]


def test_merge_never_guesses_identity_or_known_revisions():
    a = _paper("first", "a", title="Same title")
    b = _paper("second", "b", title="Same title")
    assert len(merge_paper_records(_query(), (a, b))) == 2
    known = _paper("first", "a", doi="10.1234/x", revision="v1")
    unknown = _paper("second", "b", doi="10.1234/x", revision=None)
    assert len(merge_paper_records(_query(), (known, unknown))) == 2
    linked = _paper("first", "a", doi="10.1234/x", alias="stable")
    alias = _paper("second", "b", alias="stable")
    assert len(merge_paper_records(_query(), (linked, alias))) == 1
    conflict = _paper("second", "b", doi="10.1234/y", alias="stable")
    with pytest.raises(ValueError, match="conflicting DOI"):
        merge_paper_records(_query(), (linked, conflict))
    with pytest.raises(ValueError, match="undeclared provider"):
        merge_paper_records(_query(), (_paper("other", "1"),))
    with pytest.raises(ValueError, match="conflicting records"):
        merge_paper_records(_query(), (a, _paper("first", "a", title="Changed")))


def test_same_provider_conflicts_refuse_without_invented_precedence():
    first = _paper("first", "1", title="First", doi="10.1234/a")
    other = _paper("first", "2", title="Other", doi="10.1234/a")
    with pytest.raises(ValueError, match="conflicting field"):
        merge_paper_records(_query(), (first, other))


def test_merge_omits_signed_offers_and_redacts_provider_reference():
    record = _paper("first", "a").model_copy(
        update={
            "reference": ProviderReference(
                provider_id="first",
                record_id="a",
                original_id="https://example.test/paper?token=secret",
            ),
            "document_offers": (
                DocumentOffer(
                    provider_id="first",
                    url="https://example.test/file?signature=secret",
                    media_type="application/pdf",
                ),
                DocumentOffer(
                    provider_id="first",
                    url="https://example.test/public.pdf",
                    media_type="application/pdf",
                ),
            ),
        }
    )
    (merged,) = merge_paper_records(_query(), (record,))
    assert merged.references[0].original_id == "https://example.test/paper"
    assert [offer.url for offer in merged.document_offers] == [
        "https://example.test/public.pdf"
    ]
    assert "secret" not in merged.model_dump_json()
