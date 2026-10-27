"""Database document source: rows to documents with a monotonic watermark."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_connector_sdk.source_connectors import (
    ConnectorCheckpoint,
    build_connector,
    universal,
)
from agent_connector_sdk.source_connectors.connectors import database
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


@pytest.mark.spec("SDK-SOURCE-INGEST-R900.2")
def test_poll_orders_integer_watermarks_numerically(sqlite_dsn: str) -> None:
    with sqlite3.connect(sqlite_dsn.removeprefix("sqlite:///")) as connection:
        connection.execute("INSERT INTO authors(id, name) VALUES (10, 'Ten')")
        connection.execute("INSERT INTO authors(id, name) VALUES (100, 'Hundred')")
    source = _source(sqlite_dsn)
    first = source.poll(ConnectorCheckpoint(watermark="2"))
    assert [doc.text for doc in first.documents] == ["Ten", "Hundred"]
    assert first.checkpoint.watermark == "100"
    assert source.poll(first.checkpoint).documents == []


def test_poll_refuses_a_watermark_type_change(sqlite_dsn: str) -> None:
    source = _source(sqlite_dsn)
    with pytest.raises(ValueError, match="watermark types"):
        source.poll(ConnectorCheckpoint(watermark="2026-01-01"))


@pytest.mark.spec("SDK-SOURCE-INGEST-R900.7")
def test_poll_orders_offset_timestamps_by_instant(tmp_path: Path) -> None:
    path = tmp_path / "timestamps.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE events (id INTEGER, text TEXT, updated TEXT)")
        connection.executemany(
            "INSERT INTO events VALUES (?, ?, ?)",
            [
                (1, "Earlier", "2026-01-01T10:00:00+00:00"),
                (2, "Later", "2026-01-01T06:00:00-05:00"),
            ],
        )
    source = build_connector(
        "database",
        {
            "query": "SELECT id, text, updated FROM events",
            "updated_field": "updated",
            "conn": UniversalConnector(f"sqlite:///{path}"),
        },
    )
    result = source.poll(ConnectorCheckpoint(watermark="2026-01-01T10:00:00+00:00"))
    assert [doc.text for doc in result.documents] == ["Later"]
    assert result.checkpoint.watermark == "2026-01-01T06:00:00-05:00"
    assert source.poll(result.checkpoint).documents == []


def test_poll_refuses_incomparable_timestamps() -> None:
    with pytest.raises(ValueError, match="incomparable"):
        database._watermark_after("2026-01-01T10:00:00", "2026-01-01T09:00:00Z")
    with pytest.raises(ValueError, match="incomparable"):
        database._watermark_after("2026-01-99T10:00:00Z", "2026-01-01T09:00:00Z")


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


@pytest.mark.spec("SDK-SOURCE-INGEST-R900.3")
def test_database_profile_resolution_reaches_the_tls_governed_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential_calls: dict[str, object] = {}
    tls_calls: dict[str, object] = {}
    resolver = object()
    profile = (
        '{"dsn":"postgresql://u@db.example.test/app","tls_profile_ref":"env://DB_TLS"}'
    )

    def resolve_secret(reference: str, passed_resolver: object) -> str:
        credential_calls.update(reference=reference, resolver=passed_resolver)
        return profile

    def resolve_tls(service: str, **kwargs: object) -> SimpleNamespace:
        tls_calls.update(service=service, **kwargs)
        return SimpleNamespace(
            psycopg_kwargs=lambda: {"sslmode": "verify-full"},
            cleanup=lambda: tls_calls.update(cleaned=True),
        )

    driver = SimpleNamespace(connect=lambda dsn, **kwargs: (dsn, kwargs))
    monkeypatch.setattr(database, "default_credential_resolver", lambda: resolver)
    monkeypatch.setattr(database, "resolve_secret_reference", resolve_secret)
    monkeypatch.setattr(universal, "resolve_tls_profile", resolve_tls)

    source = build_connector(
        "database",
        {"query": "SELECT 1", "connection_profile_ref": "env://DB_PROFILE"},
    )
    connection = source._connection()
    monkeypatch.setattr(connection, "_driver", lambda: driver)
    assert connection._connect() == (
        "postgresql://u@db.example.test/app",
        {"sslmode": "verify-full"},
    )
    assert credential_calls == {"reference": "env://DB_PROFILE", "resolver": resolver}
    assert tls_calls["service"] == "postgres"
    assert tls_calls["profile_ref"] == "env://DB_TLS"
    assert tls_calls["resolver"] is resolver
    assert tls_calls["cleaned"] is True


def test_row_cap_overflow_fails_closed(sqlite_dsn: str) -> None:
    with pytest.raises(RuntimeError, match="row cap"):
        list(_source(sqlite_dsn, max_rows=1).load())
