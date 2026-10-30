"""Linear metadata scanning for legacy web fetch."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import product

_META_START = re.compile(r"<meta", re.IGNORECASE)
_ATTR_START = re.compile(r"(property|name|content)=[\"']", re.IGNORECASE)
_ATTR_VALUE = re.compile(r"[^\"']*[\"']")


@dataclass(frozen=True, slots=True)
class _Attribute:
    name: str
    value: str
    start: int
    end: int
    last_gt: int


def _tag_end(html: str, start: int) -> int:
    quote = ""
    for index in range(start, len(html)):
        char = html[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == ">":
            return index + 1
    return -1


def _tags(html: str) -> list[tuple[_Attribute, ...]]:
    tags: list[tuple[_Attribute, ...]] = []
    next_start = 0
    for match in _META_START.finditer(html):
        if match.start() < next_start:
            continue
        end = _tag_end(html, match.end())
        if end < 0:
            break
        tags.append(tuple(_attributes(html[match.start() : end])))
        next_start = end
    return tags


def _attributes(tag: str) -> Iterator[_Attribute]:
    offset = 0
    last_gt = -1
    for match in _ATTR_START.finditer(tag):
        found = tag.rfind(">", offset, match.start())
        if found >= 0:
            last_gt = found
        offset = match.start()
        value = _ATTR_VALUE.match(tag, match.end())
        if value is not None:
            yield _Attribute(
                match.group(1).lower(),
                value.group()[:-1],
                match.start(),
                value.end(),
                last_gt,
            )


def _is_key(attribute: _Attribute, kind: str, key: str) -> bool:
    return (
        attribute.name == kind
        and re.fullmatch(re.escape(key), attribute.value, re.IGNORECASE) is not None
    )


def _after(attribute: _Attribute, first_end: int | None) -> bool:
    return (
        first_end is not None
        and attribute.start > first_end
        and attribute.last_gt < first_end
    )


def _key_first(tag: tuple[_Attribute, ...], kind: str, key: str) -> str | None:
    first_end: int | None = None
    result: str | None = None
    for attribute in tag:
        if (
            first_end is None
            and attribute.start > 5
            and attribute.last_gt < 0
            and _is_key(attribute, kind, key)
        ):
            first_end = attribute.end
        if (
            attribute.name == "content"
            and attribute.value
            and _after(attribute, first_end)
        ):
            result = attribute.value
    return result


def _content_first(tag: tuple[_Attribute, ...], kind: str, key: str) -> str | None:
    first_end: int | None = None
    first_value = ""
    result: str | None = None
    for attribute in tag:
        if (
            attribute.name == "content"
            and attribute.value
            and attribute.start > 5
            and attribute.last_gt < 0
        ):
            first_end, first_value = attribute.end, attribute.value
        if _after(attribute, first_end) and _is_key(attribute, kind, key):
            result = first_value
    return result


def _first_match(
    tags: list[tuple[_Attribute, ...]], kind: str, key: str, *, key_first: bool
) -> str | None:
    match = _key_first if key_first else _content_first
    for tag in tags:
        result = match(tag, kind, key)
        if result is not None:
            return result
    return None


def _find_value(
    tags: list[tuple[_Attribute, ...]],
    keys: tuple[str, ...],
    decode: Callable[[str], str],
) -> str:
    for key, kind, key_first in product(keys, ("property", "name"), (True, False)):
        result = _first_match(tags, kind, key, key_first=key_first)
        if result is not None and result.strip():
            return decode(result.strip())
    return ""


def _extract_metadata(html: str, decode: Callable[[str], str]) -> dict[str, str]:
    tags = _tags(html)
    return {
        "title": _find_value(tags, ("og:title", "twitter:title"), decode),
        "description": _find_value(
            tags, ("og:description", "twitter:description", "description"), decode
        ),
        "image": _find_value(tags, ("og:image", "twitter:image"), decode),
        "site_name": _find_value(tags, ("og:site_name",), decode),
    }
