"""Shared fixtures for the document-source connector tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from scion_sdk.source_connectors.registry import set_activation_gate


@pytest.fixture(autouse=True)
def _open_gate() -> Iterator[None]:
    """Certify every connector so a test can build it."""
    set_activation_gate(lambda _source: True)
    yield
    set_activation_gate(None)


@pytest.fixture
def sqlite_dsn(tmp_path) -> str:
    """A sqlite database with two tables joined by a foreign key."""
    import sqlite3

    path = tmp_path / "app.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE books (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, author_id INTEGER,
                FOREIGN KEY (author_id) REFERENCES authors(id)
            );
            INSERT INTO authors(id, name) VALUES (1, 'Ada'), (2, 'Grace');
            INSERT INTO books(id, title, author_id) VALUES (1, 'Notes', 1);
            """
        )
    return f"sqlite:///{path}"
