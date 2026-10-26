"""Universal database connector: one bounded read-only SELECT, schema as a ChangeSet."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from typing import Any

import pytest

from agent_connector_sdk.source_connectors import universal
from agent_connector_sdk.source_connectors.universal import (
    UniversalConnector,
    infer_kind,
)


@pytest.mark.parametrize(
    ("dsn", "kind"),
    [
        ("postgresql://u@h/db", "postgresql"),
        ("postgres://h/db", "postgresql"),
        ("mariadb://h/db", "mysql"),
        ("sqlserver://h/db", "mssql"),
        ("oracle://h/db", "oracle"),
        ("sqlite:///x.db", "sqlite"),
        ("mongodb://h/db", "mongodb"),
    ],
)
def test_kind_is_inferred_from_the_scheme(dsn: str, kind: str) -> None:
    assert infer_kind(dsn) == kind


@pytest.mark.parametrize("dsn", ["/bare/path.db", "graphql://h/q", "redis://h"])
def test_unknown_or_missing_scheme_is_refused(dsn: str) -> None:
    with pytest.raises(ValueError):
        UniversalConnector(dsn)


@pytest.mark.spec("SDK-SOURCE-INGEST-R900.1")
def test_identity_is_an_irreversible_reference(sqlite_dsn: str) -> None:
    conn = UniversalConnector(sqlite_dsn)
    assert conn.kind == "sqlite" and conn.source_ref.startswith("pref_datasource_")
    assert sqlite_dsn not in conn.name
    assert not any(hasattr(conn, verb) for verb in ("write", "update", "delete"))


def test_read_returns_bounded_rows(sqlite_dsn: str) -> None:
    conn = UniversalConnector(sqlite_dsn)
    assert conn.read("SELECT id, name FROM authors WHERE id = ?", (1,)) == [
        {"id": 1, "name": "Ada"}
    ]
    assert len(conn.read("SELECT id FROM authors", max_rows=1)) == 1
    with pytest.raises(ValueError):
        conn.read("SELECT id FROM authors", max_rows=10_001)


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM authors",
        "SELECT 1; SELECT 2",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT * FROM authors FOR UPDATE",
        "SELECT * INTO copy FROM authors",
        "SELECT 1 -- comment",
    ],
)
def test_anything_but_one_read_only_select_is_refused(
    sqlite_dsn: str, query: str
) -> None:
    with pytest.raises(PermissionError):
        UniversalConnector(sqlite_dsn).read(query)


def test_health_check(sqlite_dsn: str, tmp_path) -> None:
    assert UniversalConnector(sqlite_dsn).health_check() is True
    assert (
        UniversalConnector(f"sqlite:///{tmp_path}/missing.db").health_check() is False
    )


@pytest.mark.spec("SDK-SOURCE-INGEST-R900.5")
def test_introspect_emits_schema_entities_without_the_location(sqlite_dsn: str) -> None:
    changes = UniversalConnector(sqlite_dsn).introspect()
    types = {entity.node_type for entity in changes.entities}
    assert {"DataSource", "Table", "Column"} <= types
    tables = {e.properties["name"] for e in changes.entities if e.node_type == "Table"}
    assert tables == {"authors", "books"}
    assert {r.relationship for r in changes.relationships} >= {
        "HAS_TABLE",
        "HAS_COLUMN",
        "FOREIGN_KEY",
    }
    assert all(sqlite_dsn not in entity.id for entity in changes.entities)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R901.3")
def test_sqlite_introspection_quotes_each_table_identifier(
    sqlite_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []
    real_quote = universal.quote_sql_identifier

    def quote(name: str, *, kind: str = "identifier") -> str:
        calls.append((name, kind))
        return real_quote(name, kind=kind)

    monkeypatch.setattr(universal, "quote_sql_identifier", quote)
    changes = UniversalConnector(sqlite_dsn).introspect()

    tables = {
        entity.properties["name"]
        for entity in changes.entities
        if entity.node_type == "Table"
    }
    assert tables == {"authors", "books"}
    assert set(calls) == {(table, "table") for table in tables}
    assert len(calls) == len(tables)


@pytest.mark.parametrize(
    ("dsn", "module"),
    [
        ("postgresql://u@h/db", "psycopg"),
        ("mysql://u@h/db", "pymysql"),
        ("oracle://u@h/db", "oracledb"),
        ("mongodb://h/db", "pymongo"),
    ],
)
def test_missing_driver_is_a_runtime_error(dsn: str, module: str) -> None:
    if importlib.util.find_spec(module) is not None:
        pytest.skip(f"{module} is installed")
    with pytest.raises(RuntimeError, match="driver is unavailable"):
        UniversalConnector(dsn).health_check() or UniversalConnector(dsn)._connect()


def test_networked_connection_uses_the_tls_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}
    trust = SimpleNamespace(
        psycopg_kwargs=lambda: {"sslmode": "verify-full"},
        cleanup=lambda: calls.setdefault("cleaned", True),
    )

    def resolve(service: str, **kwargs: Any) -> Any:
        calls["service"], calls["ref"] = service, kwargs["profile_ref"]
        return trust

    driver = SimpleNamespace(
        connect=lambda dsn, **kw: calls.setdefault("connect", (dsn, kw))
    )
    monkeypatch.setattr(universal, "resolve_tls_profile", resolve)
    conn = UniversalConnector(
        "postgresql://u@db.example.test/d", tls_profile_ref="env://TLS"
    )
    monkeypatch.setattr(conn, "_driver", lambda: driver)
    conn._connect()
    assert calls["service"] == "postgres" and calls["ref"] == "env://TLS"
    assert calls["connect"] == (conn.dsn, {"sslmode": "verify-full"})
    assert calls["cleaned"] is True
