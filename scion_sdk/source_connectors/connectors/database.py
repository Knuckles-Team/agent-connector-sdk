"""Database document source: a read query's rows become documents.

Wraps :class:`~scion_sdk.source_connectors.universal.UniversalConnector`
so each row of one read-only ``SELECT`` (or one MongoDB collection) maps to a
:class:`SourceDocument` through a declared field map. ``poll`` advances a
monotonic watermark column, binding it as a query parameter when
``watermark_param`` is set. The networked drivers come from the ``db`` extra.

The connection profile is a secret reference resolved at connect time. It
never enters durable configuration, logs, provenance or identifiers.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, cast

from scion_sdk.credentials.resolution import (
    default_credential_resolver,
    resolve_secret_reference,
)
from scion_sdk.privacy import PersistencePrivacyGuard
from scion_sdk.privacy_reference import persistence_reference

from ..base import (
    CheckpointedBatch,
    ConnectorCheckpoint,
    LoadConnector,
    PollConnector,
    SourceDocument,
    default_external_access,
)
from ..registry import logger, register_source
from ..universal import UniversalConnector
from ._database_config import (
    _validate_fields,
    _validate_max_rows,
    _validate_query_text,
    _validate_read_query,
    _validate_source_alias,
    _validated_profile_ref,
)
from ._database_profile import _parse_connection_profile, _render_connection_profile
from ._database_watermark import _max_watermark, _newer_than

_SECRET_REF_RE = re.compile(r"^(?:env|openbao)://[A-Za-z0-9_./#-]+$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,254}$")
_SOURCE_ALIAS_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")


class RowVersionEvidenceUnavailable(NotImplementedError):
    """Row-version evidence needs the graph service's evidence write."""


@register_source("database")
class DatabaseConnector(LoadConnector, PollConnector):
    """Map a database query's rows to documents.


    Config:
        connection_profile_ref: Runtime secret reference resolving to either a
            DSN string or ``{"dsn": ..., "kind": ...}``. Required unless
            ``conn`` is injected. The resolved profile never enters durable
            connector config, logs, provenance, or graph identifiers.
        kind: Optional explicit backend kind (inferred from the DSN otherwise).
        query: The SQL/Mongo query whose rows become documents (required).
        id_field / title_field / text_field: row→document field map.
        updated_field: Optional monotonic column (timestamp / incrementing id)
            used as the incremental-poll watermark.
        watermark_param: Named parameter the query binds the prior watermark to
            for incremental polling (e.g. ``:since``). When set, ``poll`` passes
            ``{watermark_param: last_watermark}`` so the query returns only new
            rows; when unset, ``poll`` re-runs the full query and filters in-memory
            by ``updated_field``.
        table: Refused. Row-version evidence is written by the graph
            service (MEDULLA-INGEST-WORKER-R901); this connector does not write it.
        conn: Optional pre-built ``UniversalConnector`` (injected for tests).
        source_alias: Optional neutral logical alias (never an endpoint/name).
        max_rows: Hard cap per load/poll request; overflow fails closed.
    """

    provider = "Database"

    def configure(
        self,
        *,
        connection_profile_ref: str = "",
        kind: str | None = None,
        query: str = "",
        id_field: str = "id",
        title_field: str = "title",
        text_field: str = "text",
        updated_field: str = "",
        watermark_param: str = "",
        table: str = "",
        source_alias: str = "database-source",
        max_rows: int = 5_000,
        conn: Any = None,
        **_: object,
    ) -> None:
        if table:
            raise RowVersionEvidenceUnavailable(
                "row-version evidence is written by the graph service "
                "(MEDULLA-INGEST-WORKER-R901); configure the database source without 'table'"
            )
        if "dsn" in _:
            raise ValueError("legacy database dsn configuration is unsupported")
        profile_ref = _validated_profile_ref(conn, connection_profile_ref)
        _validate_query_text(query)
        _validate_source_alias(source_alias)
        _validate_max_rows(max_rows)
        optional_fields = tuple(filter(None, (updated_field, watermark_param)))
        _validate_fields((id_field, title_field, text_field, *optional_fields))
        effective_kind = str(kind or "").strip().lower() or None
        _validate_read_query(query, effective_kind)
        self.connection_profile_ref = profile_ref
        self.kind = effective_kind
        self.query = query
        self.id_field = id_field
        self.title_field = title_field
        self.text_field = text_field
        self.updated_field = updated_field
        self.watermark_param = watermark_param
        self.source_alias = source_alias
        self.source_ref = persistence_reference(
            "database_source",
            f"{source_alias}\x00{profile_ref or 'injected-source'}",
        )
        self.max_rows = max_rows
        self._conn = conn
        self._privacy_guard = PersistencePrivacyGuard()
        self.external_access = default_external_access()

    def _connection(self) -> Any:
        if self._conn is not None:
            return self._conn

        logger.debug("opening database connection kind=%s", self.kind)
        resolver = default_credential_resolver()
        rendered = _render_connection_profile(
            resolve_secret_reference(self.connection_profile_ref, resolver)
        )
        resolved_dsn, profile_kind, tls_values = _parse_connection_profile(rendered)
        if self.kind and profile_kind and self.kind != profile_kind:
            raise ValueError("database connection profile kind does not match")
        self._conn = UniversalConnector(
            resolved_dsn,
            kind=self.kind or profile_kind,
            source_alias=self.source_alias,
            tls_service=tls_values[0],
            tls_profile=tls_values[1],
            tls_profile_ref=tls_values[2],
            tls_resolver=resolver,
        )
        return self._conn

    def health_check(self) -> bool:
        try:
            return bool(self._connection().health_check())
        except Exception:
            return False

    def _to_document(self, row: dict[str, Any]) -> SourceDocument | None:
        rid = row.get(self.id_field)
        text = row.get(self.text_field)
        if rid is None or not isinstance(text, str) or not text.strip():
            return None
        rendered_id = str(rid)
        if not rendered_id or len(rendered_id.encode("utf-8")) > 4_096:
            return None
        document_id = persistence_reference(
            "source_document",
            rendered_id,
            namespace=self.source_ref,
        )
        title = row.get(self.title_field)
        updated = row.get(self.updated_field) if self.updated_field else None
        clean_title, _ = self._privacy_guard.sanitize_text(
            str(title) if title else "database record"
        )
        clean_text, _ = self._privacy_guard.sanitize_text(text)
        clean_updated = None
        if updated is not None:
            clean_updated, _ = self._privacy_guard.sanitize_text(str(updated))
        return SourceDocument(
            id=document_id,
            source_uri=(f"external-source://{self.source_ref}/{document_id}"),
            title=clean_title,
            text=clean_text,
            doc_type="record",
            metadata={
                "source_system": self.kind or "database",
                "source_ref": self.source_ref,
            },
            external_access=self.external_access.model_copy(deep=True),
            updated_at=clean_updated,
        )

    def _run(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = self._connection().read(
            self.query,
            params or {},
            max_rows=self.max_rows + 1,
        )
        if len(rows) > self.max_rows:
            raise RuntimeError("database source result exceeds the configured row cap")
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("database source row is not an object")
        return cast(list[dict[str, Any]], rows)

    def _documents(self, rows: list[dict[str, Any]]) -> list[SourceDocument]:
        documents: list[SourceDocument] = []
        for row in rows:
            doc = self._to_document(row)
            if doc is None or (self.updated_field and doc.updated_at is None):
                raise ValueError("database source row lacks required fields")
            documents.append(doc)
        return documents

    # -- LoadConnector -----------------------------------------------------

    def load(self) -> Iterator[SourceDocument]:
        yield from self._documents(self._run())

    # -- PollConnector -----------------------------------------------------

    def poll(self, checkpoint: ConnectorCheckpoint | None = None) -> CheckpointedBatch:
        """Return rows newer than the watermark; advance it to the new max.

        When ``watermark_param`` is set the query binds the
        prior watermark (server-side filtering); otherwise the full result is
        filtered in-memory by ``updated_field``. The watermark advances to the max
        ``updated_at`` observed, so a re-poll with no new rows yields nothing.
        """
        prior = checkpoint.watermark if checkpoint else None
        if self.watermark_param and prior is not None:
            rows = self._run({self.watermark_param: prior})
        else:
            rows = self._run()
        documents = self._documents(rows)
        if self.updated_field and prior is not None:
            documents = _newer_than(documents, prior)
        return CheckpointedBatch(
            documents=documents,
            checkpoint=ConnectorCheckpoint(
                has_more=False, watermark=_max_watermark(documents, prior)
            ),
        )
