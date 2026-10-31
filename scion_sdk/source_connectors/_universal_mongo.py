"""MongoDB schema introspection (sampled) for the database connector."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scion_sdk.source_connectors._universal_introspect import (
    _MAX_SCHEMA_FIELDS,
    _MAX_SCHEMA_TABLES,
    _Introspection,
)
from scion_sdk.source_connectors._universal_reads import _MONGO_COLLECTION_RE
from scion_sdk.source_connectors._universal_sink import _SchemaSink


class _MongoIntrospection(_Introspection):
    """Introspect MongoDB collections from one sampled document each."""

    def _introspect_mongo(self, ds_id: str, sink: _SchemaSink) -> None:
        client = self._connect()
        try:
            self._mongo_schema(client[self._mongo_db_name()], ds_id, sink)
        finally:
            client.close()

    def _mongo_schema(self, db: Any, ds_id: str, sink: _SchemaSink) -> None:
        collections = db.list_collection_names()
        if len(collections) > _MAX_SCHEMA_TABLES:
            raise RuntimeError("database schema has too many collections")
        field_count = 0
        for raw_collection in collections:
            coll_name = self._safe_identifier(raw_collection)
            if not _MONGO_COLLECTION_RE.fullmatch(coll_name):
                continue
            coll_id = self._object_id("collection", coll_name)
            # The collection itself is a declared fact.
            sink.add_member(
                ds_id, coll_id, "Collection", {"name": coll_name}, "HAS_TABLE"
            )
            sample = db[coll_name].find_one() or {}
            if isinstance(sample, Mapping):
                field_count = self._mongo_fields(
                    sample, coll_name, coll_id, sink, field_count
                )

    def _mongo_fields(
        self,
        sample: Mapping[str, Any],
        coll_name: str,
        coll_id: str,
        sink: _SchemaSink,
        field_count: int,
    ) -> int:
        # MongoDB is schemaless: each field is inferred from ONE sampled
        # document (`find_one()`), a statistical inference from a sample,
        # unlike the SQL/SQLite HAS_COLUMN edges which read a declared schema.
        for raw_field, value in sample.items():
            field_count += 1
            if field_count > _MAX_SCHEMA_FIELDS:
                raise RuntimeError("database schema has too many fields")
            name = self._safe_identifier(raw_field)
            sink.add_member(
                coll_id,
                self._object_id("field", coll_name, name),
                "Field",
                {"name": name, "data_type": type(value).__name__[:64]},
                "HAS_COLUMN",
            )
        return field_count
