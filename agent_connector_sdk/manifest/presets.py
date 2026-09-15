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

Presets may carry additional keys that describe how records map onto the
ontology (``type_field``, ``node_id_template`` and similar). Those are applied by
the ingestion authority, not by extraction, and are kept verbatim in
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
        problems = _pagination_problems(self)
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
