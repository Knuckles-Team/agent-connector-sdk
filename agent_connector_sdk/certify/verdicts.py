"""Compare a checkout's pins with the live fingerprints of its preset tools."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agent_connector_sdk.certify.checkout import ConnectorCheckout
from agent_connector_sdk.certify.fingerprints import (
    is_empty_schema_pin,
    output_schema_digest,
    tool_name,
)
from agent_connector_sdk.manifest.live_contract import validate_preset_tool_contract
from agent_connector_sdk.manifest.loader import (
    FINGERPRINTS_FILE_NAME,
    MANIFEST_FILE_NAME,
)
from agent_connector_sdk.manifest.tool_schema import (
    COMPATIBILITY_FINGERPRINT_ALGORITHM,
    ToolSchemaContractError,
)

__all__ = ["PinStatus", "ToolVerdict", "pin_locations", "tool_verdicts"]

_logger = logging.getLogger(__name__)


class PinStatus(StrEnum):
    """The state of one preset tool's pins."""

    MATCH = "match"
    DRIFT = "drift"
    EMPTY_PIN = "empty_pin"
    UNPINNED = "unpinned"
    TOOL_UNAVAILABLE = "tool_unavailable"


@dataclass(frozen=True)
class ToolVerdict:
    """One preset tool: its pins by location, its live fingerprint and status.

    ``live`` is ``""`` when the server does not serve a certifiable definition;
    ``defect`` then says why.
    """

    tool: str
    presets: tuple[str, ...]
    pins: Mapping[str, str]
    status: PinStatus
    live: str = ""
    output_schema_sha256: str = ""
    defect: str = ""


def pin_locations(checkout: ConnectorCheckout, tool: str) -> dict[str, str]:
    """Every pin of ``tool``: the fingerprints file and each manifest preset."""
    pins = {FINGERPRINTS_FILE_NAME: checkout.tool_pins.get(tool, "")}
    pins.update(
        {
            f"{MANIFEST_FILE_NAME}#{preset}": checkout.manifest_pins.get(preset, "")
            for preset in checkout.presets_for(tool)
        }
    )
    return pins


def _status(tool: str, live: str, pins: Sequence[str]) -> PinStatus:
    if any(pin and is_empty_schema_pin(tool, pin) for pin in pins):
        return PinStatus.EMPTY_PIN
    if not all(pins):
        return PinStatus.UNPINNED
    if any(pin.strip().lower() != live for pin in pins):
        return PinStatus.DRIFT
    return PinStatus.MATCH


def _unavailable(checkout: ConnectorCheckout, tool: str, defect: str) -> ToolVerdict:
    return ToolVerdict(
        tool=tool,
        presets=checkout.presets_for(tool),
        pins=pin_locations(checkout, tool),
        status=PinStatus.TOOL_UNAVAILABLE,
        defect=defect,
    )


def _presets_for_tool(checkout: ConnectorCheckout, tool: str) -> tuple[Any, ...]:
    return tuple(preset for preset in checkout.presets.values() if preset.tool == tool)


def _catalog_defect(tool: str, matches: Sequence[Any]) -> str:
    if not tool:
        return "the server lists an unnamed tool"
    if len(matches) != 1:
        state = "does not list" if not matches else "lists more than once"
        return f"the server {state} tool {tool!r}"
    return ""


def _output_digest(checkout: ConnectorCheckout, match: Any) -> str:
    digest = output_schema_digest(match)
    if checkout.contract_only and not digest:
        raise ToolSchemaContractError("the tool has no declared output schema")
    return digest


def _verdict_status(
    checkout: ConnectorCheckout,
    tool: str,
    live: str,
    *,
    pins: Mapping[str, str],
) -> PinStatus:
    if (
        checkout.contract_only
        and checkout.pin_algorithm != COMPATIBILITY_FINGERPRINT_ALGORITHM
    ):
        return PinStatus.UNPINNED
    return _status(tool, live, list(pins.values()))


def _verdict(
    checkout: ConnectorCheckout, tool: str, matches: Sequence[Any]
) -> ToolVerdict:
    defect = _catalog_defect(tool, matches)
    if defect:
        return _unavailable(checkout, tool, defect)
    try:
        contract = validate_preset_tool_contract(
            matches,
            tool_name=tool,
            presets=_presets_for_tool(checkout, tool),
        )
        output_digest = _output_digest(checkout, matches[0])
    except ToolSchemaContractError as exc:
        _logger.warning("tool %r cannot be certified: %s", tool, exc)
        return _unavailable(checkout, tool, str(exc))
    pins = pin_locations(checkout, tool)
    live = contract.compatibility_sha256
    return ToolVerdict(
        tool=tool,
        presets=checkout.presets_for(tool),
        pins=pins,
        status=_verdict_status(checkout, tool, live, pins=pins),
        live=live,
        output_schema_sha256=output_digest,
    )


def _catalog_names(
    checkout: ConnectorCheckout,
    by_name: Mapping[str, list[Any]],
    include_missing_pins: bool,
) -> set[str]:
    names = set(checkout.tools) if include_missing_pins else set()
    if checkout.contract_only:
        names.update(by_name)
    return names


def tool_verdicts(
    checkout: ConnectorCheckout,
    tools: Sequence[Any],
    *,
    include_missing_pins: bool = True,
) -> tuple[ToolVerdict, ...]:
    """One verdict per preset tool, from the server's ``tools/list`` entries."""
    by_name: dict[str, list[Any]] = {}
    for tool in tools:
        by_name.setdefault(tool_name(tool), []).append(tool)
    names = _catalog_names(checkout, by_name, include_missing_pins)
    return tuple(
        _verdict(checkout, tool, by_name.get(tool, [])) for tool in sorted(names)
    )
