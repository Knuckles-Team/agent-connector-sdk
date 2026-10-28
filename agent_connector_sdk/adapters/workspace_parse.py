"""Offline parsers for explicitly declared workspace formats."""

from __future__ import annotations

import io
import re
from typing import Any

from agent_connector_sdk.adapters.workspace_errors import (
    WorkspaceParseError as WorkspaceParseError,
)
from agent_connector_sdk.adapters.workspace_models import WorkspaceLocation
from agent_connector_sdk.adapters.workspace_office import _read_office


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeError:
        raise WorkspaceParseError("invalid_content") from None


def _plain(data: bytes) -> tuple[WorkspaceLocation, ...]:
    return tuple(
        WorkspaceLocation(text=line, line=n)
        for n, line in enumerate(_text(data).splitlines(), 1)
    )


def _transcript(data: bytes, fmt: str) -> tuple[WorkspaceLocation, ...]:
    text = _text(data).replace("\r\n", "\n")
    if fmt == "vtt":
        if not text.startswith("WEBVTT"):
            raise WorkspaceParseError("invalid_content")
        text = text.split("\n", 1)[1] if "\n" in text else ""
    cues = []
    pattern = re.compile(
        r"^(\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3}) --> (\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})(?: .*)?$"
    )
    for block in re.split(r"\n\s*\n", text.strip()):
        if block:
            cues.append(_cue(block, pattern))
    return tuple(cues)


def _cue(block: str, pattern: re.Pattern[str]) -> WorkspaceLocation:
    lines = block.splitlines()
    if len(lines) > 1 and " --> " not in lines[0]:
        lines = lines[1:]
    match = pattern.fullmatch(lines[0]) if lines else None
    if match is None or len(lines) < 2:
        raise WorkspaceParseError("invalid_content")
    return WorkspaceLocation(text="\n".join(lines[1:]), start=match[1], end=match[2])


def _pdf(data: bytes, max_pages: int, expanded: int) -> tuple[WorkspaceLocation, ...]:
    try:
        from pypdf import PdfReader, apply_configuration
    except ImportError:
        raise WorkspaceParseError("parser_unavailable") from None
    try:
        return _pdf_read(
            data,
            max_pages,
            expanded,
            reader_type=PdfReader,
            configuration=apply_configuration,
        )
    except WorkspaceParseError:
        raise
    except Exception:
        raise WorkspaceParseError("invalid_content") from None


def _pdf_read(
    data: bytes, max_pages: int, expanded: int, *, reader_type: Any, configuration: Any
) -> tuple[WorkspaceLocation, ...]:
    with configuration(
        maximum_declared_stream_length=expanded,
        array_based_stream_maximum_output_length=expanded,
        jbig2_maximum_output_length=expanded,
        lzw_maximum_output_length=expanded,
        run_length_maximum_output_length=expanded,
        zlib_maximum_output_length=expanded,
        brotli_maximum_output_length=expanded,
        stream_decoding_work_maximum_length=expanded,
        jbig2dec_binary=None,
        disable_legacy_handling=True,
    ):
        reader = reader_type(io.BytesIO(data), strict=True)
        if len(reader.pages) > max_pages:
            raise WorkspaceParseError("limit_exceeded")
        return tuple(
            WorkspaceLocation(text=page.extract_text(), page=n)
            for n, page in enumerate(reader.pages, 1)
        )


def parse_workspace(
    data: bytes, fmt: str, *, expanded: int, max_pages: int
) -> tuple[WorkspaceLocation, ...]:
    """Parse one declared local format without following external references."""
    if fmt == "text":
        return _plain(data)
    if fmt in {"vtt", "srt"}:
        return _transcript(data, fmt)
    if fmt == "pdf":
        if not data.startswith(b"%PDF-"):
            raise WorkspaceParseError("invalid_content")
        return _pdf(data, max_pages, expanded)
    if fmt in {"docx", "xlsx"}:
        return _read_office(data, fmt, expanded)
    raise WorkspaceParseError("unsupported_type")
