"""Provider cursor and manifest authority for polled documents."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from epistemic_graph.generated.source_ingestion import SourceCheckpoint

from agent_connector_sdk.manifest.model import (
    ConnectorManifest,
    IntegrityInfo,
    PermissionsSpec,
    ProvenanceSpec,
    SchemaMapping,
)
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from agent_connector_sdk.runner.document_source import (
    DocumentObservation,
    DocumentPollAdapter,
    DocumentProviderPage,
    sync_document_source,
)
from agent_connector_sdk.testing.sinks import InMemorySink

_PIN = "a" * 64


def _manifest(
    *, acl: bool = True, mapped: bool = True, complete: bool = True
) -> ConnectorManifest:
    return ConnectorManifest(
        connector="document-agent",
        schema_mappings={
            "Document": SchemaMapping(
                ontology_class="Document",
                fields={
                    name: name
                    for name in (
                        "text",
                        "title",
                        "doc_type",
                        "metadata",
                        "external_access",
                    )
                }
                if complete
                else {},
            )
        }
        if mapped
        else {},
        permissions=PermissionsSpec(acl_fields=["external_access"] if acl else []),
        provenance=ProvenanceSpec(integrity=IntegrityInfo(hash=_PIN)),
    )


def _adapter(
    poll: Callable[[SourceCheckpoint | None], Awaitable[DocumentProviderPage]],
    *,
    manifest: ConnectorManifest | None = None,
) -> DocumentPollAdapter:
    return DocumentPollAdapter(
        manifest or _manifest(),
        stream="documents",
        mapping_key="Document",
        poll=poll,
        provider_contract_sha256=_PIN,
        server="document-agent",
        tool="poll-documents",
    )


@pytest.mark.asyncio
async def test_each_provider_page_commits_before_next_cursor_is_read() -> None:
    sink = InMemorySink()
    observed = []

    async def poll(previous: SourceCheckpoint | None) -> DocumentProviderPage:
        observed.append(previous)
        if previous is None:
            return DocumentProviderPage(
                (DocumentObservation("one", "first", metadata={"host": "127.0.0.1"}),),
                {"cursor": "next", "has_more": True},
                False,
                watermark="2026-09-26T10:00:00Z",
            )
        status = await sink.source_status("document-agent", "documents")
        assert status.accepted_checkpoint == previous
        return DocumentProviderPage(
            (DocumentObservation("two", "second"),),
            {"cursor": None, "has_more": False},
            True,
            watermark="2026-09-26T11:00:00Z",
        )

    outcome = await sync_document_source(_adapter(poll), sink, max_pages=2)
    assert outcome.pages == 2
    assert outcome.records == 2
    assert outcome.exhausted
    assert outcome.checkpoint is not None
    assert outcome.checkpoint.position == {"cursor": None, "has_more": False}
    assert outcome.checkpoint.watermark == "2026-09-26T11:00:00Z"
    assert observed[1].position == {"cursor": "next", "has_more": True}
    assert observed[1].pending_watermark == "2026-09-26T10:00:00Z"


@pytest.mark.asyncio
async def test_missing_mapping_or_acl_fails_before_poll() -> None:
    async def poll(_: SourceCheckpoint | None) -> DocumentProviderPage:
        raise AssertionError("must not poll")

    with pytest.raises(SourceContractError, match="Document mapping"):
        _adapter(poll, manifest=_manifest(mapped=False))
    with pytest.raises(SourceContractError, match="ACL field"):
        _adapter(poll, manifest=_manifest(acl=False))
    with pytest.raises(SourceContractError, match="drops a required"):
        _adapter(poll, manifest=_manifest(complete=False))


@pytest.mark.asyncio
async def test_record_uses_exact_mapping_and_quarantines_unknown_access() -> None:
    async def poll(_: SourceCheckpoint | None) -> DocumentProviderPage:
        return DocumentProviderPage(
            (
                DocumentObservation(
                    "sensitive-id", "body", external_access={"is_public": False}
                ),
            ),
            {"has_more": False},
            True,
        )

    (record,) = (await _adapter(poll).extract(None)).records
    assert (
        record.mapping_reference == "manifest:document-agent#schema_mappings/Document"
    )
    assert record.payload["external_access"]["markings"] == [
        "connector-unconfigured-acl"
    ]
    assert "sensitive-id" not in record.provenance.source_uri
    assert record.provenance.tool_schema_sha256 == _PIN


@pytest.mark.asyncio
async def test_invalid_document_and_stalled_page_do_not_advance_checkpoint() -> None:
    sink = InMemorySink()

    async def empty(_: SourceCheckpoint | None) -> DocumentProviderPage:
        return DocumentProviderPage((DocumentObservation("one", "  "),), {}, True)

    with pytest.raises(MalformedSourceDataError, match="nonempty text"):
        await sync_document_source(_adapter(empty), sink, max_pages=1)
    assert (
        await sink.source_status("document-agent", "documents")
    ).accepted_checkpoint is None

    async def stalled(_: SourceCheckpoint | None) -> DocumentProviderPage:
        return DocumentProviderPage((), None, False)

    with pytest.raises(SourceContractError, match="advance"):
        await sync_document_source(_adapter(stalled), sink, max_pages=1)
