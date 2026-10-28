import asyncio
from pathlib import Path

from fastmcp import Client, FastMCP
from live_engine import live_ingest, scoped_client  # noqa: F401

from agent_connector_sdk.adapters.paper_download import (
    DocumentAdmission,
    DocumentRefusal,
    DocumentRequest,
    PaperDocumentService,
)
from agent_connector_sdk.adapters.paper_models import DocumentOffer, DocumentReceipt
from agent_connector_sdk.adapters.paper_quota import PaperQuotaPolicy, SharedPaperQuota
from agent_connector_sdk.adapters.paper_tool import register_paper_download_tool
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


async def exercise(url, root):
    client = await scoped_client(
        ["kv:read", "kv:write", "kv:shared:read", "kv:shared:write"]
    )
    try:

        async def authorize(request, context):
            if request.tenant != "allowed":
                return None
            return DocumentAdmission(
                root=Path(root),
                http=HttpClientOptions(
                    base_url=url,
                    pin_egress=True,
                    allow_loopback=True,
                    retry=RetryPolicy(max_attempts=1),
                ),
                quota=PaperQuotaPolicy(
                    provider_id="arxiv",
                    credential_group="document-test",
                    policy_revision="v1",
                    minimum_spacing_ns=1,
                ),
            )

        service = PaperDocumentService(SharedPaperQuota(client), authorize)
        request = DocumentRequest(
            tenant="allowed",
            paper_id="doi:10.1234/test",
            revision=None,
            offer=DocumentOffer(
                provider_id="arxiv",
                url=url + "/paper?secret=abc",
                media_type="text/html",
            ),
        )
        server = FastMCP("paper-download")
        register_paper_download_tool(server, service)
        async with Client(server) as mcp:
            result = await mcp.call_tool(
                "paper_download", {"request": request.model_dump(mode="json")}
            )
            denied = await mcp.call_tool(
                "paper_download",
                {
                    "request": request.model_copy(
                        update={"tenant": "denied"}
                    ).model_dump(mode="json")
                },
            )
        assert denied.structured_content["reason"] == "unauthorized"
        return DocumentReceipt.model_validate(result.structured_content["receipt"])
    finally:
        await client.close()


def test_document_download(live_ingest, tmp_path):  # noqa: F811
    body = b"<html><body><p>Research</p></body></html>"
    with ScriptedHttpServer(
        ScriptedResponse(body=body, headers={"Content-Type": "text/html"})
    ) as server:
        receipt = asyncio.run_coroutine_threadsafe(
            exercise(server.base_url, tmp_path), live_ingest._loop
        ).result(30)
        assert (tmp_path / receipt.artifact_ref).read_bytes() == body
        assert "secret" not in receipt.source_url
        assert len(server.requests) == 1
        assert len(list(tmp_path.iterdir())) == 1


def test_document_retry_after_uses_same_quota(live_ingest, tmp_path):  # noqa: F811
    body = b"<html><body>Research</body></html>"
    with ScriptedHttpServer(
        ScriptedResponse(status=429, headers={"Retry-After": "0"}),
        ScriptedResponse(body=body, headers={"Content-Type": "text/html"}),
    ) as server:
        receipt = asyncio.run_coroutine_threadsafe(
            exercise(server.base_url, tmp_path), live_ingest._loop
        ).result(30)
        assert (tmp_path / receipt.artifact_ref).read_bytes() == body
        assert len(server.requests) == 2


async def exercise_refusal(url, root, content_type="text/html"):
    client = await scoped_client(
        ["kv:read", "kv:write", "kv:shared:read", "kv:shared:write"]
    )
    try:

        async def authorize(request, context):
            return DocumentAdmission(
                root=Path(root),
                http=HttpClientOptions(
                    base_url=url,
                    pin_egress=True,
                    allow_loopback=True,
                    retry=RetryPolicy(max_attempts=1),
                ),
                quota=PaperQuotaPolicy(
                    provider_id="arxiv",
                    credential_group="document-refusal-test",
                    policy_revision="v1",
                    minimum_spacing_ns=1,
                ),
            )

        service = PaperDocumentService(SharedPaperQuota(client), authorize)
        request = DocumentRequest(
            tenant="allowed",
            paper_id="doi:10.1234/test",
            revision=None,
            offer=DocumentOffer(
                provider_id="arxiv", url=url + "/paper", media_type=content_type
            ),
        )
        try:
            await service.download(request, None)
        except DocumentRefusal as exc:
            return exc.reason
        return "ok"
    finally:
        await client.close()


def test_login_rejected_without_artifact(live_ingest, tmp_path):  # noqa: F811
    body = b'<html><body><input type="password"></body></html>'
    with ScriptedHttpServer(
        ScriptedResponse(body=body, headers={"Content-Type": "text/html"})
    ) as server:
        reason = asyncio.run_coroutine_threadsafe(
            exercise_refusal(server.base_url, tmp_path), live_ingest._loop
        ).result(30)
        assert reason == "parse_failed"
        assert list(tmp_path.iterdir()) == []


def test_bad_digest_rejected_without_artifact(live_ingest, tmp_path):  # noqa: F811
    body = b"<html><body>Research</body></html>"
    with ScriptedHttpServer(
        ScriptedResponse(
            body=body,
            headers={
                "Content-Type": "text/html",
                "Digest": "sha-256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            },
        )
    ) as server:
        reason = asyncio.run_coroutine_threadsafe(
            exercise_refusal(server.base_url, tmp_path), live_ingest._loop
        ).result(30)
        assert reason == "integrity_failed"
        assert list(tmp_path.iterdir()) == []


def test_complete_pdf(live_ingest, tmp_path):  # noqa: F811
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    with ScriptedHttpServer(
        ScriptedResponse(
            body=buffer.getvalue(), headers={"Content-Type": "application/pdf"}
        )
    ) as server:
        reason = asyncio.run_coroutine_threadsafe(
            exercise_refusal(server.base_url, tmp_path, "application/pdf"),
            live_ingest._loop,
        ).result(30)
        assert reason == "ok"
        assert len(list(tmp_path.iterdir())) == 1


def test_metadata_fallback_preserves_provider_fields(live_ingest, tmp_path):  # noqa: F811
    from agent_connector_sdk.adapters.paper_document_metadata import (
        apply_document_fallback,
    )
    from agent_connector_sdk.adapters.paper_models import (
        FieldEvidence,
        PaperRecord,
        ProviderReference,
    )

    body = b'<html><head><title>Document title</title><meta name="author" content="Jane Doe"><meta name="description" content="Document abstract"></head><body>Research</body></html>'
    with ScriptedHttpServer(
        ScriptedResponse(body=body, headers={"Content-Type": "text/html"})
    ) as server:
        receipt = asyncio.run_coroutine_threadsafe(
            exercise(server.base_url, tmp_path), live_ingest._loop
        ).result(30)
    evidence = FieldEvidence(provider_id="arxiv", source_id="1", location="atom:title")
    paper = PaperRecord(
        canonical_id="doi:10.1234/test",
        title="Provider title",
        references=(ProviderReference(provider_id="arxiv", record_id="1"),),
        field_provenance={"title": (evidence,)},
    )
    enriched = apply_document_fallback(paper, receipt, tmp_path)
    assert enriched.title == "Provider title"
    assert enriched.authors == ("Jane Doe",)
    assert enriched.abstract == "Document abstract"
    assert enriched.field_provenance["authors"][0].document_sha256 == receipt.sha256
    assert enriched.field_provenance["title"] == (evidence,)
