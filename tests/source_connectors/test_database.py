"""Database document source: rows to documents with a monotonic watermark."""

from __future__ import annotations

import pytest

from agent_connector_sdk.source_connectors import ConnectorCheckpoint, build_connector
from agent_connector_sdk.source_connectors.connectors.database import (
    DatabaseConnector,
    RowVersionEvidenceUnavailable,
)
from agent_connector_sdk.source_connectors.universal import UniversalConnector

QUERY = "SELECT id, name AS title, name AS text, id AS updated FROM authors"


def _source(sqlite_dsn: str, **config: object):
    return build_connector(
        "database",
        {
            "query": QUERY,
            "updated_field": "updated",
            "conn": UniversalConnector(sqlite_dsn),
            **config,
        },
    )


def test_rows_become_private_documents(sqlite_dsn: str) -> None:
    source = _source(sqlite_dsn)
    assert isinstance(source, DatabaseConnector) and source.health_check()
    docs = list(source.load())
    assert [d.text for d in docs] == ["Ada", "Grace"]
    assert all(d.id.startswith("pref_source_document_") for d in docs)
    assert all(d.source_uri.startswith("external-source://") for d in docs)
    assert all(d.external_access.is_public is False for d in docs)


# spec: SDK-SOURCE-INGEST-R900.6
@pytest.mark.spec("SDK-SOURCE-INGEST-R900.2")
def test_poll_advances_the_watermark_and_is_idempotent(sqlite_dsn: str) -> None:
    source = _source(sqlite_dsn)
    first = source.poll(ConnectorCheckpoint(watermark="1"))
    assert [d.text for d in first.documents] == ["Grace"]
    assert first.checkpoint.watermark == "2"
    assert source.poll(first.checkpoint).documents == []


# spec: SDK-SOURCE-INGEST-R900.4
@pytest.mark.parametrize(
    ("config", "error"),
    [
        ({"query": "DELETE FROM authors"}, ValueError),
        ({"query": "SELECT 1; DROP TABLE authors"}, ValueError),
        ({"source_alias": "Bad Alias"}, ValueError),
        ({"max_rows": 0}, ValueError),
        ({"id_field": "bad field"}, ValueError),
        ({"dsn": "sqlite:///x"}, ValueError),
        ({"table": "authors"}, RowVersionEvidenceUnavailable),
    ],
)
def test_unsafe_or_unsupported_configuration_is_refused(
    sqlite_dsn: str, config: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        _source(sqlite_dsn, **config)


def test_literal_connection_values_are_refused() -> None:
    with pytest.raises(ValueError, match="connection_profile_ref"):
        build_connector(
            "database", {"query": QUERY, "connection_profile_ref": "sqlite:///x"}
        )


def test_row_cap_overflow_fails_closed(sqlite_dsn: str) -> None:
    with pytest.raises(RuntimeError, match="row cap"):
        list(_source(sqlite_dsn, max_rows=1).load())
