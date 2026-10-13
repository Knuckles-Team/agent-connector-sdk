"""Wire models for authenticated, bounded MCP schema disclosure."""

from __future__ import annotations

import hashlib
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["SchemaFragment", "SchemaManifest"]

CHUNK_BYTES = 4096
MAX_SCHEMA_BYTES = 16 * 1024 * 1024
MAX_FRAGMENT_BYTES = 32 * 1024
MAX_FRAGMENTS = (MAX_SCHEMA_BYTES + CHUNK_BYTES - 4) // (CHUNK_BYTES - 3)
MANIFEST_URI_TEMPLATE = "openapi-schema://v1/{alias}/{schema_sha256}/manifest"
FRAGMENT_URI_TEMPLATE = "openapi-schema://v1/{alias}/{schema_sha256}/fragments/{index}"
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SchemaManifest(BaseModel):
    """Exact operation, source and canonical schema identity selected by search."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: Annotated[int, Field(ge=1, le=1)]
    operation: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=512)]
    alias: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$", max_length=128)]
    source_sha256: Digest
    schema_sha256: Digest
    input_schema_sha256: Digest
    output_schema_sha256: Digest
    schema_bytes: Annotated[int, Field(ge=1, le=MAX_SCHEMA_BYTES)]
    fragment_count: Annotated[int, Field(ge=1, le=MAX_FRAGMENTS)]
    manifest_uri: str
    fragment_uri_template: str

    @model_validator(mode="after")
    def _check_uris(self) -> Self:
        values = {"alias": self.alias, "schema_sha256": self.schema_sha256}
        if self.manifest_uri != MANIFEST_URI_TEMPLATE.format(**values):
            raise ValueError("Manifest URI differs from schema identity")
        expected = FRAGMENT_URI_TEMPLATE.format(**values, index="{index}")
        if self.fragment_uri_template != expected:
            raise ValueError("Fragment URI differs from schema identity")
        return self


class SchemaFragment(SchemaManifest):
    """One ordered UTF-8 fragment; never a replacement JSON Schema."""

    index: Annotated[int, Field(ge=0, lt=MAX_FRAGMENTS)]
    fragment_sha256: Digest
    text: Annotated[str, Field(min_length=1, max_length=CHUNK_BYTES)]

    @model_validator(mode="after")
    def _check_fragment(self) -> Self:
        value = self.text.encode("utf-8")
        if self.index >= self.fragment_count or len(value) > CHUNK_BYTES:
            raise ValueError("Invalid schema fragment bounds")
        if hashlib.sha256(value).hexdigest() != self.fragment_sha256:
            raise ValueError("Corrupt schema fragment")
        return self
