"""Declarative ``mcp_tool`` sync presets (``mcp_source_presets.json``).

A preset names the MCP tool a source is extracted through, how its arguments
are assembled, where records live in the result, and how the result paginates.
It is the declarative-first extension point of RF-ADR-009 section 2.2.1: a new
API source is a preset, not code.

Pagination modes:

``none``
    One call returns every record.
``cursor``
    ``cursor_param`` carries a token read from ``cursor_path`` (or from
    ``cursor_record_field`` of the last record); ``more_path`` may gate it.
``page``
    ``page_param`` carries a page index starting at ``start_page`` and
    ``page_size_param`` the page size. ``page_kind`` may be ``number``, the one
    spelling of a page index (agent-utilities' preset vocabulary). The fleet's
    generated presets also wrote ``page`` for the same thing; that spelling is
    rejected, so one index kind has one name.
``offset``
    ``page_param`` carries a record offset starting at 0 and advancing by the
    records returned; ``page_kind`` may be ``offset``.

A page or offset sweep ends at the first page shorter than ``page_size``, so
``page_size`` must not exceed what the server returns per call.

Lifecycle and typed-entity fields are first-class because extraction must not
silently drop a provider checkpoint, relationship, or authoritative live set.
Additional ontology projection hints (``node_id_template`` and similar) remain
owned by the ingestion authority and are kept verbatim in
:attr:`ToolPreset.mapping_hints`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

__all__ = ["ToolPreset"]

_EXTRACTION_KEYS = frozenset(
    {
        "server",
        "tool",
        "action",
        "action_param",
        "params",
        "params_style",
        "params_arg",
        "arguments",
        "records_path",
        "records_is_mapping",
        "mapping_key_field",
        "id_field",
        "title_field",
        "text_field",
        "updated_field",
        "doc_type",
        "pagination",
        "cursor_param",
        "cursor_path",
        "cursor_record_field",
        "more_path",
        "page_param",
        "page_size_param",
        "page_size",
        "page_kind",
        "start_page",
        "updated_since_param",
        "max_pages",
        "mode_param",
        "record_mode",
        "node_type_field",
        "checkpoint_path",
        "content_hash_path",
        "relationships_path",
        "relationship_source_field",
        "relationship_target_field",
        "relationship_type_field",
        "relationship_properties_field",
        "reconcile_path",
        "authoritative_path",
        "withdrawals_path",
        "withdrawal_id_field",
        "withdrawal_reason_field",
        "strict_schema",
        "content_fields",
        "metadata_fields",
    }
)

_PAGE_KINDS: dict[str, frozenset[str | None]] = {
    "none": frozenset({None}),
    "cursor": frozenset({None}),
    "page": frozenset({None, "number"}),
    "offset": frozenset({None, "offset"}),
}


class ToolPreset(BaseModel):
    """One validated ``mcp_tool`` preset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    server: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    action: str = ""
    action_param: str = "action"
    params: dict[str, JsonValue] = Field(default_factory=dict)
    params_style: Literal["json", "args"] = "json"
    params_arg: str = "params_json"
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    records_path: str = ""
    records_is_mapping: bool = False
    mapping_key_field: str = "source_key"
    id_field: str = Field(default="id", min_length=1)
    title_field: str = "title"
    text_field: str = "text"
    updated_field: str = ""
    doc_type: str = "document"
    pagination: Literal["none", "cursor", "page", "offset"] = "none"
    cursor_param: str = ""
    cursor_path: str = ""
    cursor_record_field: str = ""
    more_path: str = ""
    page_param: str = ""
    page_size_param: str = ""
    page_size: int = Field(default=100, ge=1, le=10_000)
    page_kind: Literal["number", "offset"] | None = None
    start_page: int = Field(default=0, ge=0)
    updated_since_param: str = ""
    max_pages: int = Field(default=100, ge=1, le=100_000)
    mode_param: str = "mode"
    record_mode: Literal["documents", "typed_entities"] = "documents"
    node_type_field: str = ""
    checkpoint_path: str = ""
    content_hash_path: str = "content_hash"
    relationships_path: str = ""
    relationship_source_field: str = "source"
    relationship_target_field: str = "target"
    relationship_type_field: str = "relationship"
    relationship_properties_field: str = ""
    reconcile_path: str = ""
    authoritative_path: str = ""
    withdrawals_path: str = ""
    withdrawal_id_field: str = "id"
    withdrawal_reason_field: str = "reason"
    strict_schema: bool = False
    content_fields: tuple[str, ...] = ()
    metadata_fields: tuple[str, ...] = ()
    mapping_hints: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _require_record_identity(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and data.get("id_field") == "":
            raise ValueError(
                f"preset {data.get('name')!r} has an empty id_field: an mcp_tool "
                "preset must identify its records; a sweep without record "
                "identity (such as a SQL table sweep) belongs to a data-platform "
                "source adapter (RF-ADR-009 section 2.3, wave W7)"
            )
        return data

    @model_validator(mode="after")
    def _check_pagination(self) -> ToolPreset:
        problems = [*_pagination_problems(self), *_lifecycle_problems(self)]
        if problems:
            raise ValueError(f"preset {self.name!r}: {'; '.join(problems)}")
        return self

    @classmethod
    def from_mapping(cls, name: str, raw: dict[str, Any]) -> ToolPreset:
        """Build a preset from its JSON object, separating mapping hints.

        A JSON ``null`` means the key is not set, so it takes the field default.
        """
        present = {key: value for key, value in raw.items() if value is not None}
        extraction = {k: v for k, v in present.items() if k in _EXTRACTION_KEYS}
        hints = {k: v for k, v in present.items() if k not in _EXTRACTION_KEYS}
        return cls(name=name, mapping_hints=hints, **extraction)


def _pagination_problems(preset: ToolPreset) -> list[str]:
    mode = preset.pagination
    checks = (
        (
            preset.page_kind not in _PAGE_KINDS[mode],
            f"page_kind {preset.page_kind!r} does not apply to {mode} pagination",
        ),
        (
            mode == "cursor" and not preset.cursor_param,
            "cursor pagination needs cursor_param",
        ),
        (
            mode == "cursor" and not (preset.cursor_path or preset.cursor_record_field),
            "cursor pagination needs cursor_path or cursor_record_field",
        ),
        (
            mode in {"page", "offset"} and not preset.page_param,
            f"{mode} pagination needs page_param",
        ),
        (
            mode == "offset" and preset.start_page != 0,
            "offset pagination starts at offset 0; start_page does not apply",
        ),
    )
    return [message for failed, message in checks if failed]


def _lifecycle_problems(preset: ToolPreset) -> list[str]:
    return [*_entity_lifecycle_problems(preset), *_state_lifecycle_problems(preset)]


def _entity_lifecycle_problems(preset: ToolPreset) -> list[str]:
    typed = preset.record_mode == "typed_entities"
    checks = (
        (typed and not preset.node_type_field, "typed_entities needs node_type_field"),
        (
            not typed and bool(preset.node_type_field),
            "node_type_field applies only to typed_entities",
        ),
        (
            bool(preset.relationships_path) and not typed,
            "relationships_path requires typed_entities",
        ),
        (
            bool(preset.relationships_path)
            and not (
                preset.relationship_source_field
                and preset.relationship_target_field
                and preset.relationship_type_field
            ),
            "relationships need source, target, and type fields",
        ),
    )
    return [message for failed, message in checks if failed]


def _state_lifecycle_problems(preset: ToolPreset) -> list[str]:
    reconciles = bool(preset.reconcile_path or preset.authoritative_path)
    checks = (
        (
            reconciles and not (preset.reconcile_path and preset.authoritative_path),
            "reconciliation needs reconcile_path and authoritative_path",
        ),
        (
            preset.strict_schema and not preset.metadata_fields,
            "strict_schema needs metadata_fields",
        ),
        (
            bool(preset.checkpoint_path) and not preset.updated_since_param,
            "checkpoint_path requires updated_since_param",
        ),
        (
            bool(preset.withdrawals_path)
            and not (preset.withdrawal_id_field and preset.withdrawal_reason_field),
            "withdrawals need id and reason fields",
        ),
    )
    return [message for failed, message in checks if failed]
