"""Declarative ``mcp_tool`` sync presets (``mcp_source_presets.json``).

A preset names the MCP tool a source is extracted through, how its arguments
are assembled, where records live in the result, and how the result paginates.
It is the declarative-first extension point of RF-ADR-009 section 2.2.1: a new
API source is a preset, not code.

Presets may carry additional keys that describe how records map onto the
ontology (``type_field``, ``node_id_template`` and similar). Those are applied by
the ingestion authority, not by extraction, and are kept verbatim in
:attr:`ToolPreset.mapping_hints`.
"""

from __future__ import annotations

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
    }
)


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
    pagination: Literal["none", "cursor", "page"] = "none"
    cursor_param: str = ""
    cursor_path: str = ""
    cursor_record_field: str = ""
    more_path: str = ""
    page_param: str = ""
    page_size_param: str = ""
    page_size: int = Field(default=100, ge=1, le=10_000)
    page_kind: Literal["number", "offset"] = "number"
    start_page: int = Field(default=0, ge=0)
    updated_since_param: str = ""
    max_pages: int = Field(default=100, ge=1, le=100_000)
    mapping_hints: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_pagination(self) -> ToolPreset:
        if self.pagination == "cursor" and not self.cursor_param:
            raise ValueError(
                f"preset {self.name!r}: cursor pagination needs cursor_param"
            )
        if self.pagination == "cursor" and not (
            self.cursor_path or self.cursor_record_field
        ):
            raise ValueError(
                f"preset {self.name!r}: cursor pagination needs cursor_path or "
                "cursor_record_field"
            )
        if self.pagination == "page" and not self.page_param:
            raise ValueError(f"preset {self.name!r}: page pagination needs page_param")
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
