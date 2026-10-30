"""The workspace reader never follows input relationships or changes files."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from pydantic import ValidationError
from pypdf import PdfWriter

from scion_sdk.adapters.workspace_models import (
    WorkspaceFile,
    WorkspaceLocation,
    WorkspaceOutcome,
    WorkspaceRequest,
)
from scion_sdk.adapters.workspace_parse import (
    WorkspaceParseError,
    parse_workspace,
)
from scion_sdk.adapters.workspace_reader import (
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


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.20")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.23")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.56")
async def test_served_workspace_formats_and_immutable_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workspace_test_workers import offline_read

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
    request = _request(files).model_copy(update={"root_authority": str(tmp_path)})
    server = FastMCP("workspace")
    reader = WorkspaceReader(tmp_path, authority=str(tmp_path))
    monkeypatch.setattr(reader, "_read_one", offline_read)
    register_workspace_tool(server, reader)
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


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.22")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.56")
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


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.22")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.56")
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


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.56")
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


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.20")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.23")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.56")
async def test_workspace_reads_overlap_and_respect_task_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workspace_test_workers import coordinated_read, maximum_parallelism

    files = tuple(
        _entry(tmp_path, f"{index}.txt", "text", b"item") for index in range(4)
    )
    request = _request(files).model_copy(update={"root_authority": str(tmp_path)})
    reader = WorkspaceReader(tmp_path, authority=str(tmp_path))
    monkeypatch.setattr(reader, "_read_one", coordinated_read)
    outcomes = await reader.read(request)
    assert all(value.outcome == "ok" for value in outcomes)
    assert maximum_parallelism(tmp_path, files) == 2


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.22")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.56")
async def test_workspace_traversal_is_a_per_file_refusal(tmp_path: Path) -> None:
    good = _entry(tmp_path, "safe.txt", "text", b"good")
    escape = good.model_copy(update={"relative_path": "../safe.txt"})
    values = await WorkspaceReader(tmp_path, authority="root").read(
        _request((good, escape))
    )
    assert [value.reason for value in values] == [None, "access_denied"]


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.22")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.56")
async def test_workspace_deadline_reports_cancelled_files(tmp_path: Path) -> None:
    files = tuple(
        _entry(tmp_path, f"{index}.txt", "text", b"item") for index in range(2)
    )
    reader = WorkspaceReader(tmp_path, authority="root")
    request = _request(files).model_copy(
        update={"deadline_seconds": 0.001, "max_tasks": 1}
    )
    assert all(item.reason == "cancelled" for item in await reader.read(request))


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.23")
async def test_workspace_evidence_binds_file_identity_and_stays_private(
    tmp_path: Path,
) -> None:
    body = b"line one\nline two\n"
    good = _entry(tmp_path, "ok.txt", "text", body)
    broken = _entry(tmp_path, "bad.pdf", "pdf", b"not a pdf")
    (ok, bad) = await WorkspaceReader(tmp_path, authority="root").read(
        _request((good, broken))
    )
    assert ok.outcome == "ok"
    assert ok.file == good
    assert ok.elapsed_seconds >= 0
    assert [(location.text, location.line) for location in ok.locations] == [
        ("line one", 1),
        ("line two", 2),
    ]
    assert bad.outcome == "failed"
    assert bad.reason == "invalid_content"
    assert bad.locations == ()
    evidence = ok.model_dump_json() + bad.model_dump_json()
    assert str(tmp_path) not in evidence
    assert (tmp_path / "ok.txt").read_bytes() == body
    (repeat,) = await WorkspaceReader(tmp_path, authority="root").read(
        _request((good,))
    )
    assert repeat.file.sha256 == ok.file.sha256
    assert [(location.text, location.line) for location in repeat.locations] == [
        (location.text, location.line) for location in ok.locations
    ]


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.57")
@pytest.mark.parametrize("mode", ["caller", "deadline"])
async def test_cancel_stops_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    import asyncio
    import os

    from workspace_test_workers import blocking_read

    file = _entry(tmp_path, "file.txt", "text", b"item")
    request = _request((file,)).model_copy(update={"root_authority": str(tmp_path)})
    reader = WorkspaceReader(tmp_path, authority=str(tmp_path))
    assert (await reader.read(request))[0].outcome == "ok"
    request = request.model_copy(update={"deadline_seconds": 3.0})
    monkeypatch.setattr(reader, "_read_one", blocking_read)
    task = asyncio.create_task(reader.read(request))
    marker = tmp_path / "worker.pid"
    async with asyncio.timeout(20):
        while not marker.exists():
            await asyncio.sleep(0.02)
    pid = int(marker.read_text())
    if mode == "caller":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert (await task)[0].reason == "cancelled"
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def _file_dict(**changes) -> dict:
    values = {
        "relative_path": "a.txt",
        "format": "text",
        "size_bytes": 5,
        "sha256": "ab" * 32,
        "parser_revision": "1",
    }
    return {**values, **changes}


def _request_dict(files: list[dict]) -> dict:
    return {
        "tenant": "tenant",
        "root_authority": "root",
        "files": files,
        "max_tasks": 4,
        "max_file_bytes": 1024,
        "max_expanded_bytes": 2048,
        "max_pages": 10,
        "deadline_seconds": 5.0,
    }


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.19")
def test_workspace_models_bind_request_and_refuse_undeclared_formats() -> None:
    file = WorkspaceFile.model_validate(_file_dict())
    request = WorkspaceRequest.model_validate(_request_dict([file.model_dump()]))
    assert WorkspaceFile.model_validate(file.model_dump(mode="json")) == file
    assert WorkspaceRequest.model_validate(request.model_dump(mode="json")) == request
    for fmt in ("doc", "xls", "odt", "unknown"):
        with pytest.raises(ValidationError, match="format"):
            WorkspaceFile.model_validate(
                _file_dict(relative_path=f"a.{fmt}", format=fmt)
            )
    for changes in (
        {"relative_path": "/absolute"},
        {"relative_path": "a\x00b.txt"},
        {"size_bytes": 10_485_761},
        {"sha256": "AB" * 32},
        {"parser_revision": ""},
    ):
        with pytest.raises(ValidationError):
            WorkspaceFile.model_validate(_file_dict(**changes))
    duplicate = _request_dict([_file_dict(), _file_dict()])
    with pytest.raises(ValidationError, match="duplicate"):
        WorkspaceRequest.model_validate(duplicate)
    for changes in (
        {"max_tasks": 0},
        {"max_tasks": 17},
        {"max_pages": 0},
        {"deadline_seconds": 31.0},
        {"files": []},
    ):
        with pytest.raises(ValidationError):
            WorkspaceRequest.model_validate(_request_dict([_file_dict()]) | changes)
    location = WorkspaceLocation(
        text="line",
        line=1,
        page=1,
        paragraph=1,
        sheet="Notes",
        cell="A1",
        start="00:00:01.000",
        end="00:00:02.000",
    )
    assert (
        WorkspaceLocation.model_validate(location.model_dump(mode="json")) == location
    )


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.19")
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


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.57")
async def test_process_start_failure_is_reported_per_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scion_sdk.adapters import workspace_reader

    good = _entry(tmp_path, "good.txt", "text", b"good")
    failed = _entry(tmp_path, "failed.txt", "text", b"failed")
    original = workspace_reader.to_process.run_sync

    async def run_worker(func, file, request, *, cancellable):
        if file.relative_path == "failed.txt":
            raise OSError("private process startup detail")
        return await original(func, file, request, cancellable=cancellable)

    monkeypatch.setattr(workspace_reader.to_process, "run_sync", run_worker)
    results = await WorkspaceReader(tmp_path, authority="root").read(
        _request((good, failed))
    )
    assert [item.reason for item in results] == [None, "parser_unavailable"]
    assert "private process startup detail" not in results[1].model_dump_json()
