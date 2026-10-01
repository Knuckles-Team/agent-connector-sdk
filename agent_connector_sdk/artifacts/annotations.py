"""Map MCP declarations into epistemic-graph's generated pack annotations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from epistemic_graph.generated.connector_pack import PackAnnotations
from pydantic import ValidationError

from agent_connector_sdk.manifest.tool_schema import read_field
from agent_connector_sdk.ports.errors import MalformedArtifactError

_EG_ANNOTATIONS_KEY = "eg.annotations"
_TOOL_HINTS = {
    "readOnlyHint": "read_only_hint",
    "destructiveHint": "destructive_hint",
    "idempotentHint": "idempotent_hint",
    "openWorldHint": "open_world_hint",
}
# Three-letter uppercase currency code (ISO-4217 alphabetic form). The
# generated ``DeclaredCost.currency`` field is a bare ``str``; epistemic-graph
# stores whatever it is given and never validates it, so the SDK's strict
# declaration layer is the one place a malformed currency code is caught.
_ISO_4217_RE = re.compile(r"^[A-Z]{3}$")


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump(by_alias=True, exclude_none=True, exclude_unset=True)
    if not isinstance(value, Mapping):
        raise MalformedArtifactError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _declared_annotations(value: Any) -> dict[str, Any]:
    metadata = _mapping(
        read_field(value, "_meta", "meta", attr_names=("meta", "_meta")),
        label="MCP _meta",
    )
    return _mapping(
        metadata.get(_EG_ANNOTATIONS_KEY), label=f"MCP {_EG_ANNOTATIONS_KEY}"
    )


def _merge_exact(target: dict[str, Any], field: str, value: Any) -> None:
    if value is None:
        return
    if field in target and target[field] != value:
        raise MalformedArtifactError(f"conflicting pack annotation {field!r}")
    target[field] = value


def _check_declared_bounds(annotations: PackAnnotations) -> None:
    """Fail closed on declared facts the generated schema cannot itself check.

    ``PackAnnotations`` validates presence, type and non-negativity, but
    epistemic-graph never re-derives or second-guesses a declared fact -- it
    only stores what it is told. Currency-code format and latency-band
    ordering are declaration-quality checks that belong here, in the SDK's
    strict layer, so a connector cannot publish a claim that is not even
    internally coherent.
    """
    cost = annotations.cost
    if cost is not None and not _ISO_4217_RE.match(cost.currency):
        raise MalformedArtifactError(
            f"cost.currency {cost.currency!r} is not an ISO-4217 alphabetic "
            "code (three uppercase letters, e.g. 'USD')"
        )
    latency = annotations.latency_declared
    if latency is not None and latency.p50_ms > latency.p95_ms:
        raise MalformedArtifactError(
            f"latency_declared.p50_ms ({latency.p50_ms}) exceeds "
            f"p95_ms ({latency.p95_ms})"
        )


def _validated(values: dict[str, Any]) -> PackAnnotations:
    try:
        annotations = PackAnnotations.model_validate(values)
    except ValidationError as exc:
        raise MalformedArtifactError("eg.annotations is malformed") from exc
    _check_declared_bounds(annotations)
    return annotations


def _annotations_from_mcp(
    primitive: Any,
    *,
    tool_annotations: Any = None,
    sdk_contract_pin: str | None = None,
) -> PackAnnotations:
    """Return the one generated annotation model for an MCP primitive."""
    values = _declared_annotations(primitive)
    hints = _mapping(tool_annotations, label="MCP ToolAnnotations")
    for source, target in _TOOL_HINTS.items():
        _merge_exact(values, target, hints.get(source))
    _merge_exact(values, "sdk_contract_pin", sdk_contract_pin)
    return _validated(values)


def _annotations_from_skill(front: Mapping[str, Any]) -> PackAnnotations:
    """Read the same ``eg.annotations`` declaration from skill front matter."""
    return _validated(
        _mapping(front.get(_EG_ANNOTATIONS_KEY), label="skill eg.annotations")
    )
