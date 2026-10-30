"""Check each declared preset tool against the live server."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from scion_sdk.certify.checkout import ConnectorCheckout
from scion_sdk.certify.fingerprints import output_schema_digest, tool_name
from scion_sdk.certify.read_only_check import (
    ReadOnlyOutcome,
    ToolFixture,
    check_read_only,
)
from scion_sdk.manifest.live_contract import validate_preset_tool_contract
from scion_sdk.manifest.tool_schema import ToolSchemaContractError, read_field
from scion_sdk.ports.errors import MalformedArtifactError

__all__ = ["ToolStatus", "ToolVerdict", "tool_verdicts"]

_logger = logging.getLogger(__name__)


class ToolStatus(StrEnum):
    """The state of one preset tool."""

    CERTIFIED = "certified"
    TOOL_UNAVAILABLE = "tool_unavailable"
    UNSCORED_READABLE_FORM = "unscored_readable_form"
    UNPROVEN = "unproven"
    READ_ONLY_VIOLATION = "read_only_violation"


@dataclass(frozen=True)
class ToolVerdict:
    """One preset tool: its live fingerprint and status.

    ``live`` is ``""`` when the server does not serve a certifiable definition;
    ``defect`` then says why.
    """

    tool: str
    presets: tuple[str, ...]
    status: ToolStatus
    live: str = ""
    output_schema_sha256: str = ""
    defect: str = ""


def _unavailable(checkout: ConnectorCheckout, tool: str, defect: str) -> ToolVerdict:
    return ToolVerdict(
        tool=tool,
        presets=checkout.presets_for(tool),
        status=ToolStatus.TOOL_UNAVAILABLE,
        defect=defect,
    )


def _has_readable_form(tool: Any) -> bool:
    meta = read_field(tool, "_meta", "meta", attr_names=("meta", "_meta"))
    if not isinstance(meta, Mapping):
        return False
    annotations = meta.get("eg.annotations")
    return isinstance(annotations, Mapping) and "readable_form" in annotations


def _unscored(checkout: ConnectorCheckout, tool: str) -> ToolVerdict:
    return ToolVerdict(
        tool=tool,
        presets=checkout.presets_for(tool),
        status=ToolStatus.UNSCORED_READABLE_FORM,
        defect="readable form has no verified question score",
    )


def _presets_for_tool(checkout: ConnectorCheckout, tool: str) -> tuple[Any, ...]:
    return tuple(preset for preset in checkout.presets.values() if preset.tool == tool)


def _verdict(
    checkout: ConnectorCheckout,
    tool: str,
    matches: Sequence[Any],
    *,
    fixture: ToolFixture | None,
) -> ToolVerdict:
    from scion_sdk.artifacts.tool_facts import facts_from_declaration

    if len(matches) != 1:
        state = "does not list" if not matches else "lists more than once"
        return _unavailable(checkout, tool, f"the server {state} tool {tool!r}")
    if _has_readable_form(matches[0]):
        return _unscored(checkout, tool)
    try:
        contract = validate_preset_tool_contract(
            matches,
            tool_name=tool,
            presets=_presets_for_tool(checkout, tool),
        )
        facts = facts_from_declaration(matches[0])
    except (ToolSchemaContractError, MalformedArtifactError) as exc:
        _logger.warning("tool %r cannot be certified: %s", tool, exc)
        return _unavailable(checkout, tool, str(exc))
    verdict = ToolVerdict(
        tool=tool,
        presets=checkout.presets_for(tool),
        status=ToolStatus.CERTIFIED,
        live=contract.compatibility_sha256,
        output_schema_sha256=output_schema_digest(matches[0]),
    )
    return _gate_read_only(facts, fixture, verdict)


def _gate_read_only(
    facts: Any, fixture: ToolFixture | None, verdict: ToolVerdict
) -> ToolVerdict:
    outcome = check_read_only(
        facts, fixture, tool=verdict.tool, fingerprint=verdict.live
    )
    if outcome is ReadOnlyOutcome.PROVEN:
        return verdict
    return replace(
        verdict,
        status=ToolStatus(outcome.value),
        live="",
        output_schema_sha256="",
        defect="read-only observation is missing, stale or records a write",
    )


def tool_verdicts(
    checkout: ConnectorCheckout,
    tools: Sequence[Any],
    *,
    fixtures: Mapping[str, ToolFixture] | None = None,
) -> tuple[ToolVerdict, ...]:
    """One verdict per preset tool, from the server's ``tools/list`` entries."""
    by_name: dict[str, list[Any]] = {}
    for tool in tools:
        by_name.setdefault(tool_name(tool), []).append(tool)
    verdicts = [
        _verdict(
            checkout, tool, by_name.get(tool, []), fixture=(fixtures or {}).get(tool)
        )
        for tool in checkout.tools
    ]
    verdicts.extend(_extra_verdicts(checkout, by_name, fixtures or {}))
    return tuple(verdicts)


def _extra_verdicts(
    checkout: ConnectorCheckout,
    by_name: dict[str, list[Any]],
    fixtures: Mapping[str, ToolFixture],
) -> list[ToolVerdict]:
    verdicts: list[ToolVerdict] = []
    for name in sorted(by_name.keys() - set(checkout.tools)):
        if any(_has_readable_form(tool) for tool in by_name[name]):
            verdicts.append(_unscored(checkout, name))
        elif any(_read_only_hint(tool) for tool in by_name[name]):
            verdicts.append(
                _verdict(checkout, name, by_name[name], fixture=fixtures.get(name))
            )
    return verdicts


def _read_only_hint(tool: Any) -> bool:
    """Find self-declared read-only tools outside the preset list, too."""
    from scion_sdk.artifacts.tool_facts import facts_from_declaration

    try:
        return facts_from_declaration(tool).read_only
    except MalformedArtifactError:
        return True
