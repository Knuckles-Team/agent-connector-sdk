"""Bounded, read-only database connector with schema introspection.

One driver-based connector reads SQL (PostgreSQL, MySQL, MS SQL, Oracle,
SQLite) and MongoDB through a bounded ``read`` / ``health_check`` /
``introspect`` surface. It permits one read-only ``SELECT`` per call and never
writes.

Importing this module needs no database driver. Each driver is imported when
a connection opens; install the ``db`` extra for the networked drivers. A
missing driver raises :class:`RuntimeError`. Networked connections always use
the TLS profile from :func:`~scion_sdk.tls.resolve.resolve_tls_profile`.

:meth:`UniversalConnector.introspect` returns the schema as a
:class:`~scion_sdk.ingest.model.ChangeSet` of ``DataSource``,
``Table``, ``Column`` and ``Collection`` entities. Connection values are
runtime-only: durable identifiers are irreversible persistence references and
never hold a host, account, path or credential.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import Any
from urllib.parse import urlparse

from scion_sdk.credentials.resolver import CredentialResolver
from scion_sdk.ingest.model import ChangeSet, Entity
from scion_sdk.privacy import PersistencePrivacyGuard
from scion_sdk.privacy_reference import persistence_reference
from scion_sdk.source_connectors._universal_mongo import _MongoIntrospection
from scion_sdk.source_connectors._universal_reads import _MAX_ROWS
from scion_sdk.source_connectors._universal_sink import _SchemaSink

__all__ = ["UniversalConnector", "infer_kind"]

logger = logging.getLogger(__name__)

# Supported backend kinds.
SQL_KINDS = frozenset({"postgresql", "mysql", "mssql", "oracle", "sqlite"})
SUPPORTED_KINDS = SQL_KINDS | frozenset({"mongodb"})

_SOURCE_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# Map common DSN URL schemes to a canonical ``kind``.
_SCHEME_TO_KIND: dict[str, str] = {
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "psql": "postgresql",
    "mysql": "mysql",
    "mariadb": "mysql",
    "mssql": "mssql",
    "sqlserver": "mssql",
    "oracle": "oracle",
    "oracledb": "oracle",
    "sqlite": "sqlite",
    "file": "sqlite",
    "mongodb": "mongodb",
    "mongo": "mongodb",
}


def infer_kind(dsn: str) -> str:
    """Infer the backend ``kind`` from a DSN scheme.

    A scheme is required; bare paths must be paired with ``kind="sqlite"``.
    """
    parsed = urlparse(dsn)
    scheme = (parsed.scheme or "").lower()
    if scheme and len(scheme) > 1:
        kind = _SCHEME_TO_KIND.get(scheme)
        if kind is not None:
            return kind
        raise ValueError(f"Cannot infer connector kind from DSN scheme {scheme!r}")
    raise ValueError("database connector kind requires an explicit DSN scheme")


class UniversalConnector(_MongoIntrospection):
    """Driver-based, bounded read connector for SQL and MongoDB.


    Args:
        dsn: A runtime-only data-source connection string. SQL/Mongo use a URL
            DSN; a bare sqlite path requires an explicit ``kind="sqlite"``.
        kind: Explicit backend kind; inferred from the DSN scheme when ``None``.
        source_alias: Optional non-sensitive logical alias. It participates in
            the irreversible source reference but is never persisted verbatim.
    """

    def __init__(
        self,
        dsn: str,
        kind: str | None = None,
        *,
        source_alias: str | None = None,
        tls_service: str | None = None,
        tls_profile: str | None = None,
        tls_profile_ref: str | None = None,
        tls_resolver: CredentialResolver | None = None,
    ) -> None:
        if not isinstance(dsn, str) or not dsn or len(dsn.encode("utf-8")) > 8_192:
            raise ValueError("database connection value is invalid")
        if "\x00" in dsn:
            raise ValueError("database connection value is invalid")
        if source_alias is not None and not _SOURCE_ALIAS_RE.fullmatch(source_alias):
            raise ValueError("source_alias must be a short logical identifier")
        self.dsn = dsn
        self.kind = (kind or infer_kind(dsn)).lower()
        if self.kind not in SUPPORTED_KINDS:
            raise ValueError("database connector kind is not supported")
        identity = source_alias or dsn
        self.source_ref = persistence_reference("datasource", identity)
        self.name = f"universal:{self.kind}:{self.source_ref}"
        self._tls_service = tls_service
        self._tls_profile = tls_profile
        self._tls_profile_ref = tls_profile_ref
        self._tls_resolver = tls_resolver

    def read(
        self,
        query: str,
        params: Any = None,
        *,
        max_rows: int = _MAX_ROWS,
    ) -> list[dict[str, Any]]:
        """Execute a read query and return rows as a list of dicts.

        For SQL backends ``query`` is SQL; for MongoDB ``query`` is a
        ``"collection"`` name and params is an optional bounded filter dict.
        """
        if not isinstance(max_rows, int) or isinstance(max_rows, bool):
            raise ValueError("max_rows is invalid")
        if not 1 <= max_rows <= _MAX_ROWS:
            raise ValueError("max_rows is outside the supported range")
        if self.kind in SQL_KINDS:
            self._validate_sql_read(query)
            self._validate_params(params)
            return self._sql_read(query, params, max_rows=max_rows)
        if self.kind == "mongodb":
            return self._mongo_read(query, params, max_rows=max_rows)
        raise RuntimeError("database read kind is unsupported")

    def health_check(self) -> bool:
        """Return True if a trivial round-trip to the backend succeeds."""
        try:
            return self._probe()
        except Exception as exc:
            logger.debug(
                "database health check failed kind=%s error_type=%s",
                self.kind,
                type(exc).__name__,
            )
            return False

    def _probe(self) -> bool:
        if self.kind in SQL_KINDS:
            self._sql_read("SELECT 1", None, max_rows=1)
            return True
        if self.kind == "mongodb":
            client = self._connect()
            try:
                client.admin.command("ping")
                return True
            finally:
                client.close()
        return False

    def introspect(self) -> ChangeSet:
        """Return the data source's schema as a :class:`ChangeSet` of entities and relationships.

        Best-effort and tolerant: the ``DataSource`` node is always emitted; any
        per-table/collection/type failure is logged and skipped rather than
        aborting the whole introspection.
        """
        ds_id = f"datasource:{self.source_ref}"
        sink = _SchemaSink(
            nodes=[
                Entity(
                    id=ds_id,
                    node_type="DataSource",
                    properties={"kind": self.kind, "source_ref": self.source_ref},
                )
            ]
        )
        try:
            self._populate_schema(ds_id, sink)
        except Exception as exc:  # pragma: no cover - defensive best-effort
            logger.warning(
                "database introspection partially failed kind=%s error_type=%s",
                self.kind,
                type(exc).__name__,
            )
        return self._sanitized_changeset(sink)

    def _populate_schema(self, ds_id: str, sink: _SchemaSink) -> None:
        if self.kind == "sqlite":
            self._introspect_sqlite(ds_id, sink)
        elif self.kind in SQL_KINDS:
            self._introspect_sql(ds_id, sink)
        elif self.kind == "mongodb":
            self._introspect_mongo(ds_id, sink)

    @staticmethod
    def _sanitized_changeset(sink: _SchemaSink) -> ChangeSet:
        privacy_guard = PersistencePrivacyGuard()
        entities = []
        for node in sink.nodes:
            clean, _ = privacy_guard.sanitize(dict(node.properties))
            entities.append(
                dataclasses.replace(
                    node, properties=clean if isinstance(clean, dict) else {}
                )
            )
        return ChangeSet(entities=tuple(entities), relationships=tuple(sink.edges))
