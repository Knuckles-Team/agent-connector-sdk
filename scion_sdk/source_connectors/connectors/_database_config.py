"""Configuration validation for the database document source."""

from __future__ import annotations

import re
from typing import Any

_SECRET_REF_RE = re.compile(r"^(?:env|openbao)://[A-Za-z0-9_./#-]+$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,254}$")
_SOURCE_ALIAS_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")


def _validated_profile_ref(conn: Any, connection_profile_ref: str) -> str:
    profile_ref = str(connection_profile_ref or "").strip()
    secret_ref = _SECRET_REF_RE.fullmatch(profile_ref) is not None
    if conn is None and not secret_ref:
        raise ValueError("DatabaseConnector requires a runtime connection_profile_ref")
    if conn is not None and profile_ref and not secret_ref:
        raise ValueError("literal database connection values are not supported")
    return profile_ref


def _validate_query_text(query: str) -> None:
    if not query:
        raise ValueError("DatabaseConnector requires a 'query'")
    if len(query.encode("utf-8")) > 65_536 or "\x00" in query:
        raise ValueError("DatabaseConnector query is invalid")


def _validate_max_rows(max_rows: Any) -> None:
    if not isinstance(max_rows, int) or isinstance(max_rows, bool):
        raise ValueError("DatabaseConnector max_rows is invalid")
    if not 1 <= max_rows <= 9_999:
        raise ValueError("DatabaseConnector max_rows is out of range")


def _validate_fields(fields: tuple[str, ...]) -> None:
    if any(not _FIELD_RE.fullmatch(value) for value in fields):
        raise ValueError("DatabaseConnector field mapping is invalid")


def _validate_source_alias(source_alias: str) -> None:
    if not _SOURCE_ALIAS_RE.fullmatch(source_alias):
        raise ValueError("DatabaseConnector source_alias is invalid")


def _validate_read_query(query: str, kind: str | None) -> None:
    """Reject obvious mutating or stacked SQL at the ingestion boundary.

    This is defense in depth; production credentials must still be granted
    read-only database permissions. Mongo's ``query`` is a collection name,
    while SQL ingestion deliberately accepts one plain ``SELECT`` only.
    """
    value = query.strip()
    if kind == "mongodb":
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", value):
            raise ValueError("Mongo source query must be a collection name")
        return
    if value.endswith(";"):
        value = value[:-1].rstrip()
    if (
        not re.match(r"(?is)^select\b", value)
        or ";" in value
        or "--" in value
        or "/*" in value
        or re.search(r"(?is)\binto\b", value)
        or re.search(r"(?is)\bfor\s+(update|share)\b", value)
    ):
        raise ValueError("Database ingestion requires one read-only SELECT query")
