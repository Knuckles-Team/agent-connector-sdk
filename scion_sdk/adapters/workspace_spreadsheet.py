"""Read worksheet cells using local package relationships only."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from typing import Any

from scion_sdk.adapters.workspace_errors import WorkspaceParseError
from scion_sdk.adapters.workspace_models import WorkspaceLocation

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _target(item: Any, files: dict[str, bytes]) -> tuple[str, str] | None:
    if item.get("TargetMode") == "External":
        return None
    identifier, target = item.get("Id"), item.get("Target")
    if not identifier or not target or not item.get("Type", "").endswith("/worksheet"):
        return None
    path = posixpath.normpath(posixpath.join("xl", target.lstrip("/")))
    if target.startswith("/"):
        path = posixpath.normpath(target.lstrip("/"))
    if not path.startswith("xl/worksheets/") or path not in files:
        raise WorkspaceParseError("invalid_content")
    return identifier, path


def _sheets(
    files: dict[str, bytes], parse: Callable[[bytes], Any]
) -> list[tuple[str, str]]:
    required = ("xl/workbook.xml", "xl/_rels/workbook.xml.rels", "[Content_Types].xml")
    if any(name not in files for name in required):
        raise WorkspaceParseError("invalid_content")
    targets: dict[str, str] = {}
    for item in parse(files[required[1]]).iter(_REL + "Relationship"):
        target = _target(item, files)
        if target is not None:
            if target[0] in targets:
                raise WorkspaceParseError("invalid_content")
            targets[target[0]] = target[1]
    workbook = parse(files[required[0]])
    if workbook.tag != _NS + "workbook":
        raise WorkspaceParseError("invalid_content")
    sheets = []
    for node in workbook.iter(_NS + "sheet"):
        name, identifier = node.get("name"), node.get(_DOC_REL + "id")
        if not name or identifier not in targets:
            raise WorkspaceParseError("invalid_content")
        sheets.append((name, targets[identifier]))
    return sheets


def _shared(files: dict[str, bytes], parse: Callable[[bytes], Any]) -> list[str]:
    if "xl/sharedStrings.xml" not in files:
        return []
    return [
        "".join(node.itertext())
        for node in parse(files["xl/sharedStrings.xml"]).iter(_NS + "si")
    ]


def _shared_value(text: str, shared: list[str]) -> str:
    try:
        index = int(text)
    except ValueError:
        raise WorkspaceParseError("invalid_content") from None
    if index < 0 or index >= len(shared):
        raise WorkspaceParseError("invalid_content")
    return shared[index]


def _cell(cell: Any, name: str, shared: list[str]) -> WorkspaceLocation:
    coordinate = cell.get("r")
    if coordinate is None or not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]*", coordinate):
        raise WorkspaceParseError("invalid_content")
    if cell.get("t") == "inlineStr":
        inline = cell.find(_NS + "is")
        text = "" if inline is None else "".join(inline.itertext())
    else:
        value = cell.find(_NS + "v")
        text = "" if value is None or value.text is None else value.text
        if cell.get("t") == "s":
            text = _shared_value(text, shared)
    return WorkspaceLocation(text=text, sheet=name, cell=coordinate)


def _read_spreadsheet(
    files: dict[str, bytes], parse: Callable[[bytes], Any]
) -> tuple[WorkspaceLocation, ...]:
    """Read local workbook relationships and values without fetching resources."""
    shared = _shared(files, parse)
    return tuple(
        _cell(cell, name, shared)
        for name, path in _sheets(files, parse)
        for cell in parse(files[path]).iter(_NS + "c")
    )
