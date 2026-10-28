"""Deterministic document metadata fallback for an authorized artifact."""

from __future__ import annotations

import hashlib
import os
import stat
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, BinaryIO

from agent_connector_sdk.adapters.paper_document_errors import DocumentRefusal
from agent_connector_sdk.adapters.paper_models import (
    DocumentReceipt,
    FieldEvidence,
    PaperRecord,
)


class _Metadata(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, tuple[str, str]] = {}
        self.in_title = False
        self.title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.in_title |= tag == "title"
        if tag != "meta":
            return
        data = dict(attrs)
        name = (data.get("name") or "").casefold()
        content = (data.get("content") or "").strip()
        field = {"description": "abstract", "author": "authors"}.get(name)
        if field and content and field not in self.values:
            self.values[field] = (content, "html:meta:" + name)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)


def apply_document_fallback(
    record: PaperRecord, receipt: DocumentReceipt, root: Path
) -> PaperRecord:
    """Fill missing fields only, with digest-bound deterministic provenance.

    The caller must already have authorized the tenant and storage root. An
    unreadable or changed artifact refuses instead of returning fabricated data.
    """
    if record.canonical_id != receipt.paper_id or record.revision != receipt.revision:
        raise DocumentRefusal("integrity_failed")
    suffix = ".pdf" if receipt.media_type == "application/pdf" else ".html"
    if receipt.artifact_ref != receipt.sha256 + suffix:
        raise DocumentRefusal("integrity_failed")
    try:
        values = _read_metadata(root, receipt)
    except Exception:
        raise DocumentRefusal("parse_failed") from None
    updates: dict[str, Any] = {}
    provenance = dict(record.field_provenance)
    for field, (value, location) in values.items():
        if getattr(record, field):
            continue
        updates[field] = (value,) if field == "authors" else value
        provenance[field] = (
            FieldEvidence(
                provider_id="document",
                source_id=receipt.artifact_ref,
                location=location,
                document_sha256=receipt.sha256,
            ),
        )
    updates["field_provenance"] = provenance
    try:
        return PaperRecord.model_validate({**record.model_dump(), **updates})
    except ValueError:
        raise DocumentRefusal("parse_failed") from None


def _read_metadata(root: Path, receipt: DocumentReceipt) -> dict[str, tuple[str, str]]:
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(
            receipt.artifact_ref,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    with os.fdopen(fd, "rb") as source:
        return _read_verified(source, receipt)


def _read_verified(
    source: BinaryIO, receipt: DocumentReceipt
) -> dict[str, tuple[str, str]]:
    before = os.fstat(source.fileno())
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("artifact is not a regular file")
    checksum = hashlib.sha256()
    size = 0
    while block := source.read(65536):
        size += len(block)
        if size > receipt.byte_count:
            raise ValueError("artifact too large")
        checksum.update(block)
    if size != receipt.byte_count or checksum.hexdigest() != receipt.sha256:
        raise ValueError("artifact changed")
    source.seek(0)
    values = _extract(source, receipt.media_type)
    after = os.fstat(source.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise ValueError("artifact changed during parsing")
    return values


def _extract(source: BinaryIO, media_type: str) -> dict[str, tuple[str, str]]:
    if media_type == "application/pdf":
        from pypdf import PdfReader

        metadata: Any = PdfReader(source, strict=True).metadata or {}
        values = {}
        for key, field in (
            ("/Title", "title"),
            ("/Author", "authors"),
            ("/Subject", "abstract"),
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                values[field] = (value.strip(), "pdf:info:" + key)
        return values
    import codecs

    parser = _Metadata()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    while block := source.read(65536):
        parser.feed(decoder.decode(block))
    parser.feed(decoder.decode(b"", final=True))
    parser.close()
    title = "".join(parser.title).strip()
    if title:
        parser.values["title"] = (title, "html:title")
    return parser.values
