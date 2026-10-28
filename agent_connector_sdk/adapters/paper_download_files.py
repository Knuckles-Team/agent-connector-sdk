"""Safe validation of complete paper artifacts."""

from __future__ import annotations

import codecs
import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from html.parser import HTMLParser
from typing import BinaryIO

from agent_connector_sdk.adapters.paper_document_errors import DocumentRefusal


def _verify_existing(directory: int, name: str, *, digest: str, size: int) -> None:
    with _directory_fd(directory):
        try:
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        except OSError:
            raise DocumentRefusal("storage_denied") from None
        with os.fdopen(fd, "rb") as source:
            _check_existing(source, digest=digest, size=size)


def _check_existing(source: BinaryIO, *, digest: str, size: int) -> None:
    info = os.fstat(source.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_size != size:
        raise DocumentRefusal("integrity_failed")
    checksum = hashlib.sha256()
    while block := source.read(65536):
        checksum.update(block)
    after = os.fstat(source.fileno())
    if checksum.hexdigest() != digest or (
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise DocumentRefusal("integrity_failed")


class _HtmlDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html = self.body = self.closed = self.password = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.html |= tag == "html"
        self.body |= tag == "body"
        self.password |= tag == "input" and any(
            k == "type" and (v or "").lower() == "password" for k, v in attrs
        )

    def handle_endtag(self, tag: str) -> None:
        self.closed |= tag == "html"


def _validate(fd: int, media_type: str) -> None:
    try:
        _validate_file(fd, media_type)
    except Exception:
        raise DocumentRefusal("parse_failed") from None


def _validate_file(fd: int, media_type: str) -> None:
    with os.fdopen(fd, "rb") as source:
        if media_type == "application/pdf":
            _validate_pdf(source)
        else:
            _validate_html(source)


def _validate_pdf(source: BinaryIO) -> None:
    from pypdf import PdfReader

    if source.read(5) != b"%PDF-":
        raise ValueError("not PDF")
    source.seek(-min(os.fstat(source.fileno()).st_size, 2048), os.SEEK_END)
    if b"%%EOF" not in source.read():
        raise ValueError("incomplete PDF")
    source.seek(0)
    reader = PdfReader(source, strict=True)
    if reader.is_encrypted or not len(reader.pages):
        raise ValueError("unreadable PDF")


def _validate_html(source: BinaryIO) -> None:
    parser = _HtmlDocument()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    while block := source.read(65536):
        parser.feed(decoder.decode(block))
    parser.feed(decoder.decode(b"", final=True))
    parser.close()
    if not parser.html or not parser.body or not parser.closed or parser.password:
        raise ValueError("incomplete or login HTML")


@contextmanager
def _directory_fd(directory: int) -> Iterator[None]:
    try:
        yield
    finally:
        os.close(directory)
