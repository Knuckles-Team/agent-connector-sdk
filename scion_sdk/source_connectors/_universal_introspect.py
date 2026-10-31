"""SQL and sqlite schema introspection for the database connector."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from scion_sdk.identifiers import quote_sql_identifier
from scion_sdk.ingest.model import Relationship
from scion_sdk.source_connectors._universal_cells import _MAX_IDENTIFIER_BYTES
from scion_sdk.source_connectors._universal_reads import _Reads
from scion_sdk.source_connectors._universal_sink import _SchemaSink

logger = logging.getLogger("scion_sdk.source_connectors.universal")

_MAX_SCHEMA_TABLES = 10_000
_MAX_SCHEMA_FIELDS = 100_000


class _Introspection(_Reads):
    """Introspect sqlite (PRAGMA) and generic SQL (information_schema)."""

    def _introspect_sqlite(self, ds_id: str, sink: _SchemaSink) -> None:
        conn = self._connect()
        try:
            self._sqlite_schema(conn.cursor(), ds_id, sink)
        finally:
            conn.close()

    def _sqlite_schema(self, cur: Any, ds_id: str, sink: _SchemaSink) -> None:
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = [
            self._safe_identifier(row[0])
            for row in cur.fetchmany(_MAX_SCHEMA_TABLES + 1)
        ]
        if len(tables) > _MAX_SCHEMA_TABLES:
            raise RuntimeError("database schema has too many tables")
        field_count = 0
        for table in tables:
            field_count = self._introspect_sqlite_table(
                cur, ds_id, table, sink, field_count
            )

    def _introspect_sqlite_table(
        self,
        cur: Any,
        ds_id: str,
        table: str,
        sink: _SchemaSink,
        field_count: int,
    ) -> int:
        table_id = self._object_id("table", table)
        sink.add_member(ds_id, table_id, "Table", {"name": table}, "HAS_TABLE")
        quoted_table = quote_sql_identifier(table, kind="table")
        field_count = self._introspect_sqlite_columns(
            cur, quoted_table, table, table_id, sink, field_count
        )
        self._introspect_sqlite_foreign_keys(cur, quoted_table, table, sink)
        return field_count

    def _introspect_sqlite_columns(
        self,
        cur: Any,
        quoted_table: str,
        table: str,
        table_id: str,
        sink: _SchemaSink,
        field_count: int,
    ) -> int:
        cur.execute(f"PRAGMA table_info({quoted_table})")
        for col in cur.fetchmany(_MAX_SCHEMA_FIELDS - field_count + 1):
            # (cid, name, type, notnull, dflt_value, pk)
            field_count += 1
            if field_count > _MAX_SCHEMA_FIELDS:
                raise RuntimeError("database schema has too many fields")
            col_name = self._safe_identifier(col[1])
            sink.add_member(
                table_id,
                self._object_id("column", table, col_name),
                "Column",
                {
                    "name": col_name,
                    "data_type": str(col[2] or "")[:_MAX_IDENTIFIER_BYTES],
                    "primary_key": bool(col[5]),
                },
                "HAS_COLUMN",
            )
        return field_count

    def _introspect_sqlite_foreign_keys(
        self,
        cur: Any,
        quoted_table: str,
        table: str,
        sink: _SchemaSink,
    ) -> None:
        cur.execute(f"PRAGMA foreign_key_list({quoted_table})")
        for fk in cur.fetchmany(_MAX_SCHEMA_FIELDS + 1):
            # (id, seq, table, from, to, on_update, on_delete, match)
            from_col = self._safe_identifier(fk[3])
            ref_table = self._safe_identifier(fk[2])
            to_col = self._safe_identifier(fk[4]) if fk[4] else ""
            src_col_id = self._object_id("column", table, from_col)
            tgt_col_id = (
                self._object_id("column", ref_table, to_col)
                if to_col
                else self._object_id("table", ref_table)
            )
            sink.edges.append(
                Relationship(
                    source=src_col_id, target=tgt_col_id, relationship="FOREIGN_KEY"
                )
            )

    def _introspect_sql(self, ds_id: str, sink: _SchemaSink) -> None:
        col_rows = self._sql_read(
            "SELECT table_name, column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema NOT IN "
            "('pg_catalog','information_schema','sys','mysql','performance_schema') "
            "ORDER BY table_name, ordinal_position",
            None,
            max_rows=_MAX_SCHEMA_FIELDS,
        )
        seen_tables: set[str] = set()
        for row in col_rows:
            self._introspect_sql_column_row(ds_id, row, sink, seen_tables)
        self._introspect_sql_foreign_keys(sink)

    def _introspect_sql_column_row(
        self,
        ds_id: str,
        row: Mapping[str, Any],
        sink: _SchemaSink,
        seen_tables: set[str],
    ) -> None:
        raw_table = row.get("table_name") or row.get("TABLE_NAME")
        raw_column = row.get("column_name") or row.get("COLUMN_NAME")
        if not raw_table or not raw_column:
            return
        table = self._safe_identifier(raw_table)
        col_name = self._safe_identifier(raw_column)
        data_type = str(row.get("data_type") or row.get("DATA_TYPE") or "")[
            :_MAX_IDENTIFIER_BYTES
        ]
        table_id = self._object_id("table", table)
        if table not in seen_tables:
            if len(seen_tables) >= _MAX_SCHEMA_TABLES:
                raise RuntimeError("database schema has too many tables")
            seen_tables.add(table)
            sink.add_member(ds_id, table_id, "Table", {"name": table}, "HAS_TABLE")
        sink.add_member(
            table_id,
            self._object_id("column", table, col_name),
            "Column",
            {"name": col_name, "data_type": data_type},
            "HAS_COLUMN",
        )

    def _introspect_sql_foreign_keys(self, sink: _SchemaSink) -> None:
        # Foreign keys (best-effort; standard information_schema join).
        try:
            self._add_sql_foreign_keys(sink)
        except Exception as exc:  # pragma: no cover - dialect variance
            logger.debug(
                "database foreign-key introspection skipped kind=%s error_type=%s",
                self.kind,
                type(exc).__name__,
            )

    def _add_sql_foreign_keys(self, sink: _SchemaSink) -> None:
        fk_rows = self._sql_read(
            "SELECT kcu.table_name AS src_table, kcu.column_name AS src_col, "
            "ccu.table_name AS ref_table, ccu.column_name AS ref_col "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name "
            "WHERE tc.constraint_type = 'FOREIGN KEY'",
            None,
            max_rows=_MAX_SCHEMA_FIELDS,
        )
        for fk in fk_rows:
            src = self._object_id(
                "column",
                self._safe_identifier(fk.get("src_table")),
                self._safe_identifier(fk.get("src_col")),
            )
            tgt = self._object_id(
                "column",
                self._safe_identifier(fk.get("ref_table")),
                self._safe_identifier(fk.get("ref_col")),
            )
            sink.edges.append(
                Relationship(source=src, target=tgt, relationship="FOREIGN_KEY")
            )
