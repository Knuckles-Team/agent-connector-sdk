"""Identifier validation for names interpolated into Cypher, SQL or DDL text.

Query languages bind values but not identifiers, so a label, table or column
name must be written into the query text. These helpers are the one gate for
such names. :class:`InvalidIdentifierError` never echoes the rejected value.

* :func:`validate_identifier`: graph labels, relationship types and property
  keys, ASCII only, at most 128 characters.
* :func:`validate_sql_identifier` / :func:`quote_sql_identifier`: SQL names,
  at most 63 bytes so a long name cannot silently truncate into another.
"""

from __future__ import annotations

import re

__all__ = [
    "InvalidIdentifierError",
    "quote_sql_identifier",
    "validate_identifier",
    "validate_sql_identifier",
]

CYPHER_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class InvalidIdentifierError(ValueError):
    """An identifier failed validation; only ``kind`` is reported."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"invalid {kind} identifier")


def _checked(name: object, pattern: re.Pattern[str], kind: str) -> str:
    rendered = str(name) if name is not None else ""
    if not pattern.fullmatch(rendered):
        raise InvalidIdentifierError(kind)
    return rendered


def validate_identifier(name: object, kind: str = "label") -> str:
    """Return ``name`` as text when it is a valid graph identifier."""
    return _checked(name, CYPHER_IDENTIFIER_RE, kind)


def validate_sql_identifier(name: object, kind: str = "table") -> str:
    """Return ``name`` as text when it is a valid SQL identifier."""
    return _checked(name, SQL_IDENTIFIER_RE, kind)


def quote_sql_identifier(name: object, kind: str = "table") -> str:
    """Validate ``name`` and return it double-quoted, ready to embed."""
    return '"' + validate_sql_identifier(name, kind).replace('"', '""') + '"'
