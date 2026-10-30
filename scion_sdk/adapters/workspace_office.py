"""Read office ZIPs without extracting paths or following references."""

from __future__ import annotations

import io
import zipfile
from typing import Any

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from scion_sdk.adapters.workspace_errors import WorkspaceParseError
from scion_sdk.adapters.workspace_models import WorkspaceLocation
from scion_sdk.adapters.workspace_spreadsheet import _read_spreadsheet


def _members(archive: zipfile.ZipFile, expanded: int) -> dict[str, bytes]:
    infos = archive.infolist()
    if len(infos) > 1024 or sum(item.file_size for item in infos) > expanded:
        raise WorkspaceParseError("limit_exceeded")
    if len({item.filename for item in infos}) != len(infos):
        raise WorkspaceParseError("invalid_content")
    contents = {}
    used = 0
    for item in infos:
        with archive.open(item) as stream:
            body = stream.read(expanded - used + 1)
        used += len(body)
        if used > expanded or len(body) != item.file_size:
            raise WorkspaceParseError("limit_exceeded")
        contents[item.filename] = body
    return contents


def _archive(data: bytes, expanded: int) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise WorkspaceParseError("invalid_content") from None
    try:
        with archive:
            return _members(archive, expanded)
    except (zipfile.BadZipFile, OSError, RuntimeError):
        raise WorkspaceParseError("invalid_content") from None


def _parse_xml(data: bytes) -> Any:
    """Reject XML entities before parsing local office content."""
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise WorkspaceParseError("invalid_content")
    try:
        return ElementTree.fromstring(data)
    except (ElementTree.ParseError, DefusedXmlException):
        raise WorkspaceParseError("invalid_content") from None


def _docx(files: dict[str, bytes]) -> tuple[WorkspaceLocation, ...]:
    body = files.get("word/document.xml")
    if body is None or "[Content_Types].xml" not in files:
        raise WorkspaceParseError("invalid_content")
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = _parse_xml(body)
    if root.tag != namespace + "document" or root.find(namespace + "body") is None:
        raise WorkspaceParseError("invalid_content")
    return tuple(
        WorkspaceLocation(text="".join(node.itertext()), paragraph=n)
        for n, node in enumerate(root.iter(namespace + "p"), 1)
    )


def _read_office(data: bytes, fmt: str, expanded: int) -> tuple[WorkspaceLocation, ...]:
    """Read only locally contained office data."""
    files = _archive(data, expanded)
    if fmt == "docx":
        return _docx(files)
    return _read_spreadsheet(files, _parse_xml)
