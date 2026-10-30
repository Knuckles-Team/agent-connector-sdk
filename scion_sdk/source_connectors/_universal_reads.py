"""Bounded SQL and MongoDB reads for the database connector."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from scion_sdk.source_connectors._universal_connect import _Connections

_MAX_RESULT_BYTES = 16 * 1_048_576
_MAX_ROWS = 10_000
_MAX_COLUMNS = 512
_FETCH_BATCH = 128
_MONGO_COLLECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")


class _Reads(_Connections):
    """Execute bounded reads against SQL and MongoDB backends."""

    def _sql_read(
        self,
        query: str,
        params: Any,
        *,
        max_rows: int = _MAX_ROWS,
    ) -> list[dict[str, Any]]:
        self._validate_sql_read(query)
        self._validate_params(params)
        conn = self._connect()
        try:
            return self._fetch_rows(conn, query, params, max_rows)
        finally:
            conn.close()

    def _fetch_rows(
        self, conn: Any, query: str, params: Any, max_rows: int
    ) -> list[dict[str, Any]]:
        cur = conn.cursor()
        cur.execute(query, params or ())
        description = cur.description or []
        if len(description) > _MAX_COLUMNS:
            raise RuntimeError("database result has too many columns")
        cols = [self._safe_identifier(item[0]) for item in description]
        output: list[dict[str, Any]] = []
        total_bytes = 0
        while len(output) < max_rows:
            chunk = cur.fetchmany(min(_FETCH_BATCH, max_rows - len(output)))
            if not chunk:
                break
            for row in chunk:
                total_bytes += sum(self._bounded_cell_size(cell) for cell in row)
                if total_bytes > _MAX_RESULT_BYTES:
                    raise RuntimeError("database result exceeds the configured bound")
                output.append(dict(zip(cols, row, strict=False)))
        return output

    def _mongo_db_name(self) -> str:
        parsed = urlparse(self.dsn)
        return self._safe_identifier((parsed.path or "").lstrip("/") or "test")

    def _mongo_read(
        self,
        collection: str,
        params: Any,
        *,
        max_rows: int,
    ) -> list[dict[str, Any]]:
        if not isinstance(collection, str) or not _MONGO_COLLECTION_RE.fullmatch(
            collection
        ):
            raise ValueError("MongoDB collection is invalid")
        query_filter = params or {}
        if not isinstance(query_filter, Mapping):
            raise ValueError("MongoDB filter must be an object")
        self._validate_params(query_filter)
        self._validate_mongo_filter(query_filter)
        client = self._connect()
        try:
            return self._mongo_read_rows(client, collection, query_filter, max_rows)
        finally:
            client.close()

    def _mongo_read_rows(
        self,
        client: Any,
        collection: str,
        query_filter: Mapping[str, Any],
        max_rows: int,
    ) -> list[dict[str, Any]]:
        db = client[self._mongo_db_name()]
        output: list[dict[str, Any]] = []
        total_bytes = 0
        for document in db[collection].find(dict(query_filter)).limit(max_rows):
            if not isinstance(document, Mapping):
                continue
            item = dict(document)
            total_bytes += sum(
                len(str(key).encode("utf-8")) + self._bounded_cell_size(value)
                for key, value in item.items()
            )
            if total_bytes > _MAX_RESULT_BYTES:
                raise RuntimeError("database result exceeds the configured bound")
            output.append(item)
        return output
