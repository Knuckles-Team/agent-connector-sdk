"""Offline bookmark reads retain source provenance and refuse unsafe input."""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from pydantic import ValidationError

from agent_connector_sdk.adapters.bookmark_models import (
    BookmarkEnvelope,
    BookmarkRequest,
    BookmarkResult,
)
from agent_connector_sdk.adapters.bookmark_source import (
    BookmarkReader,
    BookmarkReadError,
    register_bookmark_tool,
)
from agent_connector_sdk.vendor_extractors import social


def _request(path: str = "bookmarks.json") -> BookmarkRequest:
    return BookmarkRequest(
        relative_path=path, export_revision="social-v1", vocabulary_revision="v1"
    )


def _records() -> list[dict[str, Any]]:
    return [
        {
            "id": "post-1",
            "text": "An offline post",
            "entities": {
                "hashtags": [{"tag": "Example"}],
                "user_mentions": [{"username": "Person"}],
                "urls": [
                    {"expanded_url": "https://github.com/project"},
                    {"expanded_url": "https://unknown.example/item"},
                ],
            },
        }
    ]


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.7")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.8")
async def test_served_read_is_stable_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("offline reader attempted network access")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    row = _records()[0]
    (tmp_path / "bookmarks.json").write_text(json.dumps({"bookmarks": [row, row]}))
    reader = BookmarkReader(
        tmp_path, vocabulary_revision="v1", domains={"github.com": "developer"}
    )
    expected = await reader.read(_request())
    assert isinstance(expected, BookmarkResult)
    assert (
        expected.file_sha256
        == hashlib.sha256((tmp_path / "bookmarks.json").read_bytes()).hexdigest()
    )
    assert len(expected.bookmarks) == 1
    bookmark = expected.bookmarks[0]
    assert isinstance(bookmark, BookmarkEnvelope)
    assert bookmark.source_offset == 0
    assert bookmark.hashtags == ("example",)
    assert bookmark.mentions == ("person",)
    assert bookmark.tools == ("GitHub",)
    assert bookmark.domains == (("github.com", "developer"), ("unknown.example", None))
    assert bookmark.raw == row
    monkeypatch.setitem(social.KNOWN_TOOL_DOMAINS, "github.com", "Changed")
    assert expected == await reader.read(_request())
    server = FastMCP("bookmark-fixture")
    register_bookmark_tool(server, reader)
    async with Client(server) as client:
        result = await client.call_tool(
            "bookmarks_read", {"request": _request().model_dump(mode="json")}
        )
    assert result.structured_content == expected.model_dump(mode="json")


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.7")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.8")
async def test_reader_refuses_invalid_and_escaping_files(tmp_path: Path) -> None:
    reader = BookmarkReader(tmp_path, vocabulary_revision="v1", domains={})
    for path in ("../outside", "/absolute", "a//b", "a/./b"):
        with pytest.raises(BookmarkReadError, match="access_denied"):
            await reader.read(_request(path))
    (tmp_path / "outside").write_text(json.dumps({"bookmarks": _records()}))
    (tmp_path / "link").symlink_to(tmp_path / "outside")
    with pytest.raises(BookmarkReadError, match="access_denied"):
        await reader.read(_request("link"))
    for text in (
        '{"bookmarks":[],"bookmarks":[]}',
        '{"bookmarks":[{"id":"p","text":NaN}]}',
        '{"other":[]}',
    ):
        (tmp_path / "bookmarks.json").write_text(text)
        with pytest.raises(BookmarkReadError):
            await reader.read(_request())
    (tmp_path / "bookmarks.json").write_text(
        json.dumps(
            {"bookmarks": [{"id": "same", "text": "a"}, {"id": "same", "text": "b"}]}
        )
    )
    with pytest.raises(BookmarkReadError, match="invalid_content"):
        await reader.read(_request())


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.7")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.8")
async def test_continuation_binds_file_digest_and_preserves_offsets(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bookmarks.json"
    rows = [
        {"id": "item-0", "text": "entry 0"},
        {"id": "item-0", "text": "entry 0"},
        {"id": "item-1", "text": "entry 1"},
        {"id": "item-2", "text": "entry 2"},
    ]
    path.write_text(json.dumps(rows))
    reader = BookmarkReader(tmp_path, vocabulary_revision="v1", domains={})
    first = await reader.read(_request().model_copy(update={"page_size": 2}))
    assert [row.source_offset for row in first.bookmarks] == [0, 2]
    assert first.next_offset == 3
    continuation = _request().model_copy(
        update={
            "offset": 3,
            "file_sha256": first.file_sha256,
            "vocabulary_sha256": first.vocabulary_sha256,
            "page_size": 2,
        }
    )
    second = await reader.read(continuation)
    assert [row.source_offset for row in second.bookmarks] == [3]
    assert second.next_offset is None
    other_vocabulary = BookmarkReader(
        tmp_path, vocabulary_revision="v1", domains={"example.org": "other"}
    )
    with pytest.raises(BookmarkReadError, match="invalid_content"):
        await other_vocabulary.read(continuation)
    path.write_text(json.dumps([*rows, {"id": "new", "text": "new"}]))
    with pytest.raises(BookmarkReadError, match="invalid_content"):
        await reader.read(continuation)
    with pytest.raises(ValidationError, match="digests"):
        BookmarkRequest(
            relative_path="a",
            export_revision="social-v1",
            vocabulary_revision="v1",
            offset=1,
        )
    with pytest.raises(ValidationError):
        BookmarkRequest(
            relative_path="a", export_revision="unknown", vocabulary_revision="v1"
        )

    (tmp_path / "bookmarks.json").write_text(
        json.dumps(
            {"bookmarks": [{"id": "x", "text": "x", "entities": {"urls": "malformed"}}]}
        )
    )
    with pytest.raises(BookmarkReadError, match="invalid_content"):
        await reader.read(_request())


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.7")
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.8")
async def test_limits_and_authorized_directories(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="root must be absolute"):
        BookmarkReader(Path("relative"), vocabulary_revision="v1", domains={})
    reader = BookmarkReader(tmp_path, vocabulary_revision="v1", domains={})
    path = tmp_path / "bookmarks.json"
    path.write_text(json.dumps([{"id": "x", "text": "a" * 70_000}]))
    with pytest.raises(BookmarkReadError, match="limit_exceeded"):
        await reader.read(_request())
    with pytest.raises(BookmarkReadError, match="limit_exceeded"):
        await reader.read(_request().model_copy(update={"max_file_bytes": 128}))
    folder = tmp_path / "nested"
    folder.mkdir()
    (folder / "file.json").write_text("[]")
    assert (await reader.read(_request("nested/file.json"))).bookmarks == ()
    (tmp_path / "folder-link").symlink_to(folder, target_is_directory=True)
    with pytest.raises(BookmarkReadError, match="access_denied"):
        await reader.read(_request("folder-link/file.json"))
