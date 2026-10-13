"""Public exact schema transport for generated providers and MCP consumers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .schema_disclosure_models import (
    CHUNK_BYTES,
    FRAGMENT_URI_TEMPLATE,
    MANIFEST_URI_TEMPLATE,
    MAX_FRAGMENT_BYTES,
    MAX_SCHEMA_BYTES,
    SchemaFragment,
    SchemaManifest,
)

__all__ = [
    "SchemaDisclosure",
    "SchemaFragment",
    "SchemaManifest",
    "build_schema_disclosure",
    "read_schema_fragment",
    "reconstruct_schema",
]


def _encoded(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _chunks(payload: bytes) -> tuple[str, ...]:
    parts, start = [], 0
    while start < len(payload):
        end = min(start + CHUNK_BYTES, len(payload))
        while end < len(payload) and payload[end] & 0xC0 == 0x80:
            end -= 1
        parts.append(payload[start:end].decode("utf-8"))
        start = end
    return tuple(parts)


@dataclass(frozen=True)
class SchemaDisclosure:
    """Provider snapshot produced by build_schema_disclosure."""

    manifest: SchemaManifest
    parts: tuple[str, ...]


def build_schema_disclosure(
    schemas: tuple[dict[str, Any], dict[str, Any]],
    *,
    operation: str,
    alias: str,
    source_sha256: str,
) -> SchemaDisclosure:
    inputs, outputs = schemas
    payload = _encoded({"inputSchema": inputs, "outputSchema": outputs})
    if not 0 < len(payload) <= MAX_SCHEMA_BYTES:
        raise ValueError("Schema exceeds bounded fragment transport")
    parts = _chunks(payload)
    digest = _digest(payload)
    manifest = SchemaManifest(
        version=1,
        operation=operation,
        alias=alias,
        source_sha256=source_sha256,
        schema_sha256=digest,
        input_schema_sha256=_digest(_encoded(inputs)),
        output_schema_sha256=_digest(_encoded(outputs)),
        schema_bytes=len(payload),
        fragment_count=len(parts),
        manifest_uri=MANIFEST_URI_TEMPLATE.format(alias=alias, schema_sha256=digest),
        fragment_uri_template=FRAGMENT_URI_TEMPLATE.format(
            alias=alias, schema_sha256=digest, index="{index}"
        ),
    )
    return SchemaDisclosure(manifest=manifest, parts=parts)


def read_schema_fragment(
    disclosure: SchemaDisclosure, index: int, *, expected_sha256: str
) -> dict[str, Any]:
    manifest = disclosure.manifest
    if expected_sha256 != manifest.schema_sha256:
        raise ValueError("Stale or mismatched schema identity")
    if type(index) is not int or not 0 <= index < len(disclosure.parts):
        raise ValueError("Invalid schema fragment index")
    part = disclosure.parts[index]
    result = SchemaFragment(
        **manifest.model_dump(),
        index=index,
        fragment_sha256=_digest(part.encode()),
        text=part,
    ).model_dump()
    if len(_encoded(result)) > MAX_FRAGMENT_BYTES:
        raise ValueError("Schema fragment envelope exceeds disclosure budget")
    return result


def _fragment_bytes(
    value: dict[str, Any], manifest: SchemaManifest, index: int
) -> bytes:
    if len(_encoded(value)) > MAX_FRAGMENT_BYTES:
        raise ValueError("Schema fragment envelope exceeds disclosure budget")
    part = SchemaFragment.model_validate(value)
    identity = part.model_dump(exclude={"index", "fragment_sha256", "text"})
    if identity != manifest.model_dump() or part.index != index:
        raise ValueError("Cross-operation, stale, duplicate or reordered fragment")
    return part.text.encode("utf-8")


def reconstruct_schema(
    manifest: dict[str, Any], fragments: list[dict[str, Any]]
) -> dict[str, Any]:
    """Reconstruct against the independently selected authenticated manifest."""
    selected = SchemaManifest.model_validate(manifest)
    if len(fragments) != selected.fragment_count:
        raise ValueError("Incomplete schema fragments")
    payload = b"".join(
        _fragment_bytes(part, selected, index) for index, part in enumerate(fragments)
    )
    if (
        len(payload) != selected.schema_bytes
        or _digest(payload) != selected.schema_sha256
    ):
        raise ValueError("Schema reconstruction differs from selected manifest")
    result = _verify_document(json.loads(payload), selected)
    if _encoded(result) != payload:
        raise ValueError("Noncanonical schema reconstruction")
    return result


def _verify_document(value: Any, manifest: SchemaManifest) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"inputSchema", "outputSchema"}:
        raise ValueError("Invalid reconstructed schema document")
    expected = {
        "inputSchema": manifest.input_schema_sha256,
        "outputSchema": manifest.output_schema_sha256,
    }
    for key, digest in expected.items():
        if not isinstance(value[key], dict) or _digest(_encoded(value[key])) != digest:
            raise ValueError("Reconstructed input/output schema identity differs")
    return value
