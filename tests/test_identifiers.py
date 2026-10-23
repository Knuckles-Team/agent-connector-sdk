"""Identifier validation for names interpolated into query text."""

from __future__ import annotations

import pytest

from agent_connector_sdk.identifiers import (
    InvalidIdentifierError,
    quote_sql_identifier,
    validate_identifier,
    validate_sql_identifier,
)

HOSTILE = [
    "",
    None,
    "1abc",
    "x; DROP TABLE t--",
    'a"b',
    "a`b",
    "\uff41bc",
    "a b",
    "a-b",
]


# spec: SDK-CONNECTOR-CONTROL-R901.4
@pytest.mark.parametrize("name", HOSTILE)
@pytest.mark.parametrize("check", [validate_identifier, validate_sql_identifier])
def test_hostile_names_are_refused_without_echo(check, name: object) -> None:
    with pytest.raises(InvalidIdentifierError) as exc:
        check(name, kind="column")
    assert exc.value.kind == "column" and str(exc.value) == "invalid column identifier"


def test_length_ceilings_differ_for_graph_and_sql() -> None:
    assert validate_identifier("a" * 128) == "a" * 128
    with pytest.raises(InvalidIdentifierError):
        validate_identifier("a" * 129)
    assert validate_sql_identifier("a" * 63) == "a" * 63
    with pytest.raises(InvalidIdentifierError):
        validate_sql_identifier("a" * 64)


def test_quote_sql_identifier_returns_a_quoted_name() -> None:
    assert quote_sql_identifier("Orders_2026") == '"Orders_2026"'
