"""Exact paper identities without title similarity or semantic inference."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import quote

from scion_sdk.adapters.paper_provider import ProviderPaper

_DOI = re.compile(r"^10\.\d{4,9}/\S+$")


def _doi(value: str) -> str:
    value = value.strip()
    lower = value.casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lower.startswith(prefix):
            lower = lower.removeprefix(prefix)
            break
    if not _DOI.fullmatch(lower):
        raise ValueError("invalid DOI")
    return lower


def _identity_tokens(record: ProviderPaper) -> tuple[str, ...]:
    values = [
        "provider:"
        + quote(record.reference.provider_id, safe="")
        + ":"
        + quote(record.reference.record_id, safe="")
    ]
    if record.doi is not None:
        values.append("doi:" + _doi(record.doi))
    if record.canonical_alias is not None:
        values.append("alias:" + record.canonical_alias)
    return tuple(values)


def _root(parent: list[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _groups(records: tuple[ProviderPaper, ...]) -> list[list[ProviderPaper]]:
    parent = list(range(len(records)))
    owners: dict[tuple[str | None, str], int] = {}
    for index, record in enumerate(records):
        for token in _identity_tokens(record):
            key = (record.revision, token)
            previous = owners.setdefault(key, index)
            parent[_root(parent, index)] = _root(parent, previous)
    grouped: dict[int, list[ProviderPaper]] = {}
    for index, record in enumerate(records):
        grouped.setdefault(_root(parent, index), []).append(record)
    _check_group_dois(grouped.values())
    return list(grouped.values())


def _check_group_dois(groups: Iterable[list[ProviderPaper]]) -> None:
    for group in groups:
        dois = {
            token
            for record in group
            for token in _identity_tokens(record)
            if token.startswith("doi:")
        }
        if len(dois) > 1:
            raise ValueError("alias binds conflicting DOI identities")
