"""Read a bounded social export without following paths or outbound links.

The host supplies an authorized storage root and immutable local vocabulary.
This reader does not authenticate callers or create graph checkpoints.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from agent_connector_sdk.adapters.bookmark_io import _read_file
from agent_connector_sdk.adapters.bookmark_models import (
    BookmarkEnvelope,
    BookmarkReadError,
    BookmarkRequest,
    BookmarkResult,
)
from agent_connector_sdk.adapters.bookmark_parse import _parse, _validated_record
from agent_connector_sdk.vendor_extractors import social

__all__ = ["BookmarkReadError", "BookmarkReader", "register_bookmark_tool"]


def _domain(url: str) -> str | None:
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def _vocabulary_entry(host: str, category: str) -> bool:
    return (
        isinstance(host, str)
        and bool(host)
        and len(host) <= 253
        and host == host.lower()
        and isinstance(category, str)
        and bool(category)
        and len(category) <= 256
    )


class BookmarkReader:
    """Read one explicit social-v1 export from the host-authorized root."""

    def __init__(
        self, root: Path, *, vocabulary_revision: str, domains: Mapping[str, str]
    ) -> None:
        if not vocabulary_revision or len(vocabulary_revision) > 256:
            raise ValueError("vocabulary revision is required")
        self._root = Path(root)
        if not self._root.is_absolute():
            raise ValueError("authorized root must be absolute")
        self._revision = vocabulary_revision
        self._domains = dict(domains)
        self._tools = dict(social.KNOWN_TOOL_DOMAINS)
        if len(self._domains) > 10_000 or any(
            not _vocabulary_entry(host, category)
            for host, category in self._domains.items()
        ):
            raise ValueError("invalid vocabulary")
        encoded = json.dumps(
            {
                "revision": self._revision,
                "domains": self._domains,
                "tools": self._tools,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._vocabulary_digest = hashlib.sha256(encoded).hexdigest()

    async def read(self, request: BookmarkRequest) -> BookmarkResult:
        """Return stable records; no URLs are fetched or instructions executed."""
        request = BookmarkRequest.model_validate(request.model_dump())
        if request.vocabulary_revision != self._revision:
            raise BookmarkReadError("unsupported_type")
        if (
            request.vocabulary_sha256 is not None
            and request.vocabulary_sha256 != self._vocabulary_digest
        ):
            raise BookmarkReadError("invalid_content")
        data = await asyncio.to_thread(
            _read_file, self._root, request.relative_path, request.max_file_bytes
        )
        digest = hashlib.sha256(data).hexdigest()
        if request.file_sha256 is not None and request.file_sha256 != digest:
            raise BookmarkReadError("invalid_content")
        return self._result(_parse(data), request, digest)

    def _result(
        self, rows: list[dict[str, Any]], request: BookmarkRequest, digest: str
    ) -> BookmarkResult:
        if request.offset > len(rows):
            raise BookmarkReadError("invalid_content")
        records: list[BookmarkEnvelope] = []
        seen: dict[str, bytes] = {}
        for offset, raw in enumerate(rows):
            identity, text, encoded = _validated_record(raw)
            if identity in seen:
                if seen[identity] != encoded:
                    raise BookmarkReadError("invalid_content")
                continue
            seen[identity] = encoded
            if offset < request.offset:
                continue
            if len(records) == request.page_size:
                return self._page(digest, records, offset)
            records.append(self._envelope(raw, request, digest, offset, identity, text))
        return self._page(digest, records, None)

    def _page(
        self, digest: str, records: list[BookmarkEnvelope], next_offset: int | None
    ) -> BookmarkResult:
        return BookmarkResult(
            file_sha256=digest,
            vocabulary_sha256=self._vocabulary_digest,
            bookmarks=tuple(records),
            next_offset=next_offset,
        )

    def _envelope(
        self,
        raw: dict[str, Any],
        request: BookmarkRequest,
        digest: str,
        offset: int,
        identity: str,
        text: str,
    ) -> BookmarkEnvelope:
        extracted = social.extract(
            {"record": raw, "document_id": identity, "tool_domains": self._tools}
        )
        values: dict[str, list[str]] = {"Hashtag": [], "Mention": [], "Tool": []}
        for entity in extracted.entities:
            values[entity.node_type].append(str(entity.properties["name"]))
        urls = tuple(social._extract_urls(raw, ()))
        domains = tuple(
            (host, self._domains.get(host)) for url in urls if (host := _domain(url))
        )
        try:
            return BookmarkEnvelope(
                bookmark_id=identity,
                record_key=hashlib.sha256(
                    bytes.fromhex(digest) + b"\x00" + identity.encode("utf-8")
                ).hexdigest(),
                text=text,
                source_offset=offset,
                file_sha256=digest,
                export_revision=request.export_revision,
                vocabulary_revision=request.vocabulary_revision,
                vocabulary_sha256=self._vocabulary_digest,
                hashtags=tuple(values["Hashtag"]),
                mentions=tuple(values["Mention"]),
                tools=tuple(values["Tool"]),
                urls=urls,
                domains=domains,
                raw=raw,
            )
        except (TypeError, ValueError, ValidationError, RecursionError):
            raise BookmarkReadError("invalid_content") from None


def register_bookmark_tool(server: Any, reader: BookmarkReader) -> None:
    """Register a read-only operation on a host-authenticated MCP server."""

    async def bookmarks_read(request: BookmarkRequest) -> BookmarkResult:
        """Read a local social-v1 bookmark export."""
        return await reader.read(request)

    server.tool(name="bookmarks_read", annotations={"readOnlyHint": True})(
        bookmarks_read
    )
