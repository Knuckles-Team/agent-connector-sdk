"""The workspace reader never follows input relationships or changes files."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from pypdf import PdfWriter

from agent_connector_sdk.adapters.workspace_models import (
    WorkspaceFile,
    WorkspaceLocation,
    WorkspaceOutcome,
    WorkspaceRequest,
)
from agent_connector_sdk.adapters.workspace_parse import (
    WorkspaceParseError,
    parse_workspace,
)
from agent_connector_sdk.adapters.workspace_reader import (
    WorkspaceReader,
    register_workspace_tool,
)


def _zip(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


def _entry(root: Path, name: str, fmt: str, body: bytes) -> WorkspaceFile:
    (root / name).write_bytes(body)
    return WorkspaceFile(
        relative_path=name,
        format=fmt,
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        parser_revision="1",
    )


def _request(files: tuple[WorkspaceFile, ...]) -> WorkspaceRequest:
    return WorkspaceRequest(
        tenant="tenant",
        root_authority="root",
        files=files,
        max_tasks=2,
        max_file_bytes=10_485_760,
        max_expanded_bytes=1_000_000,
        max_pages=100,
        deadline_seconds=30.0,
    )


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.56")
async def test_served_workspace_formats_and_immutable_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def deny_network(*args, **kwargs):
        raise AssertionError("workspace parser attempted network access")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    word = _zip(
        {
            "[Content_Types].xml": "<Types/>",
            "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>',
        }
    )
    book = _zip(
        {
            "[Content_Types].xml": "<Types/>",
            "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Notes" r:id="rId2"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet9.xml"/></Relationships>',
            "xl/worksheets/sheet9.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Cell</t></is></c></row></sheetData></worksheet>',
        }
    )
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf = io.BytesIO()
    writer.write(pdf)
    files = (
        _entry(tmp_path, "a.txt", "text", b"one\ntwo\n"),
        _entry(
            tmp_path,
            "b.vtt",
            "vtt",
            b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n",
        ),
        _entry(tmp_path, "c.docx", "docx", word),
        _entry(tmp_path, "d.xlsx", "xlsx", book),
        _entry(tmp_path, "e.pdf", "pdf", pdf.getvalue()),
    )
    request = _request(files)
    server = FastMCP("workspace")
    register_workspace_tool(server, WorkspaceReader(tmp_path, authority="root"))
    async with Client(server) as client:
        result = await client.call_tool(
            "workspace_read", {"request": request.model_dump(mode="json")}
        )
    values = result.structured_content["result"]
    assert [value["outcome"] for value in values] == ["ok"] * 5
    assert values[0]["locations"][1]["line"] == 2
    assert values[1]["locations"][0]["start"] == "00:00:01.000"
    assert values[2]["locations"][0]["text"] == "Hello"
    assert (values[3]["locations"][0]["sheet"], values[3]["locations"][0]["cell"]) == (
        "Notes",
        "A1",
    )
    assert values[4]["locations"][0]["page"] == 1
    assert all(
        hashlib.sha256((tmp_path / file.relative_path).read_bytes()).hexdigest()
        == file.sha256
        for file in files
    )


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.56")
async def test_refusals_are_per_file_and_snapshot_bound(tmp_path: Path) -> None:
    good = _entry(tmp_path, "a.txt", "text", b"hello")
    changed = _entry(tmp_path, "b.txt", "text", b"original")
    (tmp_path / "b.txt").write_bytes(b"changed")
    broken = _entry(tmp_path, "c.pdf", "pdf", b"not a pdf")
    path = _entry(tmp_path, "d.txt", "text", b"file")
    (tmp_path / "d.txt").unlink()
    (tmp_path / "d.txt").symlink_to(tmp_path / "a.txt")
    outputs = await WorkspaceReader(tmp_path, authority="root").read(
        _request((good, changed, broken, path))
    )
    assert [(item.outcome, item.reason) for item in outputs] == [
        ("ok", None),
        ("failed", "invalid_content"),
        ("failed", "invalid_content"),
        ("failed", "access_denied"),
    ]
    with pytest.raises(ValueError, match="authority"):
        await WorkspaceReader(tmp_path, authority="other").read(_request((good,)))


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.56")
async def test_workspace_rejects_zip_bombs_and_unknown_parser(tmp_path: Path) -> None:
    bomb = _zip({"[Content_Types].xml": "<Types/>", "word/document.xml": "x" * 10_000})
    entry = _entry(tmp_path, "a.docx", "docx", bomb)
    unknown = _entry(tmp_path, "b.txt", "text", b"content").model_copy(
        update={"parser_revision": "other"}
    )
    mismatched = _entry(tmp_path, "c.txt", "pdf", b"%PDF-")
    request = _request((entry, unknown, mismatched)).model_copy(
        update={"max_expanded_bytes": 100}
    )
    results = await WorkspaceReader(tmp_path, authority="root").read(request)
    assert [item.reason for item in results] == [
        "limit_exceeded",
        "parser_unavailable",
        "unsupported_type",
    ]


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.56")
async def test_workspace_refuses_changed_digest_and_xml_entities(
    tmp_path: Path,
) -> None:
    word = _zip(
        {
            "[Content_Types].xml": "<Types/>",
            "word/document.xml": '<!DOCTYPE x [<!ENTITY e "expanded">]><x>&e;</x>',
        }
    )
    entry = _entry(tmp_path, "a.docx", "docx", word)
    (outcome,) = await WorkspaceReader(tmp_path, authority="root").read(
        _request((entry,))
    )
    assert outcome.reason == "invalid_content"


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.56")
async def test_workspace_reads_overlap_and_respect_task_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    files = tuple(
        _entry(tmp_path, f"{index}.txt", "text", b"item") for index in range(4)
    )
    reader = WorkspaceReader(tmp_path, authority="root")
    read_one = reader._read_one
    lock = threading.Lock()
    active = 0
    maximum = 0

    def tracked(file, request):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.05)
        try:
            return read_one(file, request)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(reader, "_read_one", tracked)
    outcomes = await reader.read(_request(files))
    assert all(value.outcome == "ok" for value in outcomes)
    assert 1 < maximum <= 2


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.56")
async def test_workspace_traversal_is_a_per_file_refusal(tmp_path: Path) -> None:
    good = _entry(tmp_path, "safe.txt", "text", b"good")
    escape = good.model_copy(update={"relative_path": "../safe.txt"})
    values = await WorkspaceReader(tmp_path, authority="root").read(
        _request((good, escape))
    )
    assert [value.reason for value in values] == [None, "access_denied"]


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.56")
async def test_workspace_deadline_reports_cancelled_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    files = tuple(
        _entry(tmp_path, f"{index}.txt", "text", b"item") for index in range(2)
    )
    reader = WorkspaceReader(tmp_path, authority="root")
    read_one = reader._read_one

    def slow(file, request):
        time.sleep(0.05)
        return read_one(file, request)

    monkeypatch.setattr(reader, "_read_one", slow)
    request = _request(files).model_copy(
        update={"deadline_seconds": 0.001, "max_tasks": 1}
    )
    assert all(item.reason == "cancelled" for item in await reader.read(request))


def test_parser_public_contract() -> None:
    locations = parse_workspace(b"example", "text", expanded=1024, max_pages=1)
    assert isinstance(locations[0], WorkspaceLocation)
    with pytest.raises(WorkspaceParseError, match="unsupported_type"):
        parse_workspace(b"x", "unknown", expanded=1024, max_pages=1)
    assert (
        WorkspaceOutcome(
            file=WorkspaceFile(
                relative_path="a.txt",
                format="text",
                size_bytes=0,
                sha256="a" * 64,
                parser_revision="1",
            ),
            outcome="ok",
            elapsed_seconds=0.0,
        ).reason
        is None
    )
