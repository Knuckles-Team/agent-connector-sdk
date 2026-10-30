"""Wire models and bounds for the foreign-read lifecycle (private sibling)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from scion_sdk.adapters._foreign_read_codec import _encoded_rows_bytes

FOREIGN_READ_SCHEMA_VERSION = 1
_MAX_ID_BYTES = 64 * 1024
_MAX_COLUMNS = 128
_MAX_COLUMN_NAME_BYTES = 256
_MAX_COLUMN_VALUE_BYTES = 64 * 1024
_MAX_PROVENANCE_ITEMS = 32
_MAX_PROVENANCE_BYTES = 4 * 1024
_U64_MAX = 2**64 - 1

ForeignReadMethod = Literal[
    "ForeignReadOpen",
    "ForeignReadChunk",
    "ForeignReadComplete",
    "ForeignReadAbort",
]
Digest256 = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[0-9a-f]{64}$",
        min_length=64,
        max_length=64,
    ),
]


class ForeignReadError(RuntimeError):
    """A refusal at the typed foreign-read boundary.

    The error intentionally carries only a closed reason and stage.  Request
    values, approval contents and transport details never enter diagnostics.
    """

    _REASONS = frozenset(
        {
            "invalid_request",
            "invalid_response",
            "schema_mismatch",
            "transport",
            "deadline",
            "expired",
            "sequence",
            "digest",
            "limit_exceeded",
            "unknown_execution",
            "terminal",
            "cancelled",
        }
    )

    def __init__(self, reason: str, stage: str = "client") -> None:
        if reason not in self._REASONS:
            reason = "transport"
        self.reason = reason
        self.stage = stage
        super().__init__(reason)


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


def _bounded_u64() -> Any:
    return Field(ge=0, le=_U64_MAX)


class ForeignReadLimits(_Strict):
    """The exact finite limits accepted by EG ``ForeignReadLimits``."""

    max_rows: int = Field(gt=0, le=250_000)
    max_bytes: int = Field(gt=0, le=64 * 1024 * 1024)
    chunk_rows: int = Field(gt=0, le=16_384)
    chunk_bytes: int = Field(gt=0, le=4 * 1024 * 1024)
    deadline_ms: int = Field(gt=0, le=60_000)


class ForeignReadExecutionRef(_Strict):
    """Server-owned opaque execution identity bound to one query digest."""

    execution_id: int = _bounded_u64()
    query_digest: Digest256


class ForeignReadSourceIdentity(_Strict):
    """Source identity issued by EG from the approved pack and current head."""

    source_ref: str = Field(min_length=1, max_length=_MAX_ID_BYTES)
    source_revision: int = _bounded_u64()
    schema_digest: Digest256
    snapshot_ref: Digest256

    @model_validator(mode="after")
    def _source_ref_bytes(self) -> ForeignReadSourceIdentity:
        if len(self.source_ref.encode()) > _MAX_ID_BYTES:
            raise ValueError("foreign-read source reference is too large")
        return self


class ForeignReadRow(_Strict):
    """One mapped row in EG's existing ``ForeignRows`` value currency."""

    id: str = Field(min_length=1, max_length=_MAX_ID_BYTES)
    score: float | None = Field(default=None, allow_inf_nan=False)
    columns: dict[str, Any] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bounded_cells(self) -> ForeignReadRow:
        if len(self.id.encode()) > _MAX_ID_BYTES:
            raise ValueError("foreign-read row id is too large")
        if len(self.columns) > _MAX_COLUMNS:
            raise ValueError("foreign-read row has too many columns")
        for name, value in self.columns.items():
            _check_column(name, value)
        if len(self.provenance) > _MAX_PROVENANCE_ITEMS or any(
            not item or len(item.encode()) > _MAX_PROVENANCE_BYTES
            for item in self.provenance
        ):
            raise ValueError("foreign-read provenance is invalid")
        return self


def _check_column(name: str, value: Any) -> None:
    if not name or len(name.encode()) > _MAX_COLUMN_NAME_BYTES:
        raise ValueError("foreign-read column name is too large")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("foreign-read column value is not JSON") from exc
    if len(encoded) > _MAX_COLUMN_VALUE_BYTES:
        raise ValueError("foreign-read column value is too large")


class ForeignReadOpenRequest(_Strict):
    """Exact EG ``ForeignReadOpenRequest``; approval remains an EG-owned DTO."""

    schema_version: int = Field(ge=0, le=65_535)
    source_name: str = Field(min_length=1, max_length=_MAX_ID_BYTES)
    approval: Any
    plan_digest: Digest256
    query_digest: Digest256
    limits: ForeignReadLimits

    @model_validator(mode="after")
    def _approval_is_opaque_dto(self) -> ForeignReadOpenRequest:
        # Do not copy or reinterpret ConnectorPackSourceApprovalResult here;
        # generated Pydantic models and mapping-shaped generated DTOs are both
        # accepted, while a scalar cannot be a producer approval record.
        if self.approval is None or (
            not isinstance(self.approval, Mapping)
            and not hasattr(self.approval, "model_dump")
        ):
            raise ValueError("foreign-read approval must be a generated DTO")
        if len(self.source_name.encode()) > _MAX_ID_BYTES:
            raise ValueError("foreign-read source name is too large")
        return self


class ForeignReadOpenResult(_Strict):
    schema_version: int = Field(ge=0, le=65_535)
    execution: ForeignReadExecutionRef
    expires_at_ms: int = _bounded_u64()
    next_sequence: int = _bounded_u64()
    source_identity: ForeignReadSourceIdentity


class ForeignReadChunkRequest(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    source_identity: ForeignReadSourceIdentity
    rows: list[ForeignReadRow] = Field(min_length=1, max_length=16_384)

    @model_validator(mode="after")
    def _bounded_wire_rows(self) -> ForeignReadChunkRequest:
        try:
            encoded = _encoded_rows_bytes(self.rows)
        except ValueError:
            raise ValueError("foreign-read rows are not encodable") from None
        if encoded > 4 * 1024 * 1024:
            raise ValueError("foreign-read chunk rows exceed the EG byte cap")
        return self


class ForeignReadChunkResult(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    accepted_rows: int = Field(ge=0, le=2**32 - 1)
    total_rows: int = _bounded_u64()
    total_bytes: int = _bounded_u64()
    next_sequence: int = _bounded_u64()


class ForeignReadCompleteRequest(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()


class ForeignReadCompleteResult(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    total_rows: int = _bounded_u64()
    total_bytes: int = _bounded_u64()


class ForeignReadAbortRequest(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    reason: str = Field(min_length=1, max_length=_MAX_ID_BYTES)

    @model_validator(mode="after")
    def _reason_bytes(self) -> ForeignReadAbortRequest:
        if len(self.reason.encode()) > _MAX_ID_BYTES:
            raise ValueError("foreign-read abort reason is too large")
        return self


class ForeignReadAbortResult(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    reason: str = Field(min_length=1, max_length=_MAX_ID_BYTES)
