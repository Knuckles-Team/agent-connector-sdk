"""Shared type aliases for the data-preparation models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

type SchemaVersion = Literal["1"]


type InvalidRowDisposition = Literal["fail", "quarantine"]


type ArrowTypeName = Literal[
    "bool",
    "int8",
    "int16",
    "int32",
    "int64",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "float32",
    "float64",
    "string",
]


type ColumnName = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[^\x00]+$"),
]


type OpaqueReference = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]


type Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


type ScalarValue = StrictBool | StrictInt | StrictFloat | StrictStr


type ProfileScalar = StrictBool | StrictInt | StrictFloat | StrictStr


type ProfileTargetKind = Literal[
    "local_arrow",
    "engine_table",
    "engine_rowset",
    "engine_subgraph",
]


type ProfileWarningCode = Literal[
    "empty_dataset",
    "all_null",
    "high_null_rate",
    "single_value",
    "high_cardinality",
    "cardinality_unavailable",
    "small_group_suppressed",
    "stats_suppressed",
    "topk_suppressed",
    "topk_truncated",
    "quantiles_unavailable",
    "quantiles_truncated",
    "deadline_exceeded",
    "profile_truncated",
]
