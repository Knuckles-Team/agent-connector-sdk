"""Partial-error allow-list helpers for the GraphQL document connector."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._graphql_base import (
    _ERROR_CODE_RE,
)
from ._graphql_paths import _valid_field_path


def _error_signature(error: Any) -> tuple[str, str] | None:
    if not isinstance(error, Mapping):
        return None
    extensions = error.get("extensions")
    code = (
        str(extensions.get("code") or "").strip().upper()
        if isinstance(extensions, Mapping)
        else ""
    )
    raw_path = error.get("path")
    if not isinstance(raw_path, list):
        return None
    path = ".".join(str(part) for part in raw_path if isinstance(part, str))
    if not _ERROR_CODE_RE.fullmatch(code) or not _valid_field_path(path):
        return None
    return code, path


def _error_is_allowlisted(
    error: Any, *, codes: tuple[str, ...], paths: tuple[str, ...]
) -> bool:
    signature = _error_signature(error)
    if signature is None:
        return False
    code, path = signature
    if code not in codes:
        return False
    return any(path == allowed or path.startswith(f"{allowed}.") for allowed in paths)


def _errors_are_allowlisted(
    errors: Any, *, codes: tuple[str, ...], paths: tuple[str, ...]
) -> bool:
    if not isinstance(errors, list) or not errors or not codes or not paths:
        return False
    return all(
        _error_is_allowlisted(error, codes=codes, paths=paths) for error in errors
    )
