"""Compare a checkout's pins with the live fingerprints of its preset tools."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agent_connector_sdk.certify.checkout import ConnectorCheckout
from agent_connector_sdk.certify.fingerprints import is_empty_schema_pin, tool_name
from agent_connector_sdk.manifest.live_contract import validate_preset_tool_contract
from agent_connector_sdk.manifest.loader import (
    FINGERPRINTS_FILE_NAME,
    MANIFEST_FILE_NAME,
)
from agent_connector_sdk.manifest.tool_schema import ToolSchemaContractError

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
    ``defect`` then says why. ``output_schema_sha256`` is the live D18 output
    pin (``""`` when the tool declares no output schema) and ``output_pin`` the
    pinned one (``None`` when the checkout pins none).
    """

    tool: str
    presets: tuple[str, ...]
    pins: Mapping[str, str]
    status: PinStatus
    live: str = ""
    output_schema_sha256: str = ""
    output_pin: str | None = None
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


def _status(
    tool: str, live: tuple[str, str], *, pins: Sequence[str], output_pin: str | None
) -> PinStatus:
    """``live`` is the live (contract, output-schema) digest pair."""
    if any(pin and is_empty_schema_pin(tool, pin) for pin in pins):
        return PinStatus.EMPTY_PIN
    if not all(pins) or output_pin is None:
        return PinStatus.UNPINNED
    pinned = [pin.strip().lower() for pin in pins]
    if any(pin != live[0] for pin in pinned) or output_pin.lower() != live[1]:
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


def _verdict(
    checkout: ConnectorCheckout, tool: str, matches: Sequence[Any]
) -> ToolVerdict:
    if len(matches) != 1:
        state = "does not list" if not matches else "lists more than once"
        return _unavailable(checkout, tool, f"the server {state} tool {tool!r}")
    try:
        contract = validate_preset_tool_contract(
            matches,
            tool_name=tool,
            presets=_presets_for_tool(checkout, tool),
        )
    except ToolSchemaContractError as exc:
        _logger.warning("tool %r cannot be certified: %s", tool, exc)
        return _unavailable(checkout, tool, str(exc))
    pins = pin_locations(checkout, tool)
    output_pin = checkout.output_pins.get(tool)
    live = (contract.compatibility_sha256, contract.output_schema_sha256)
    return ToolVerdict(
        tool=tool,
        presets=checkout.presets_for(tool),
        pins=pins,
        status=_status(tool, live, pins=list(pins.values()), output_pin=output_pin),
        live=live[0],
        output_schema_sha256=live[1],
        output_pin=output_pin,
    )


def tool_verdicts(
    checkout: ConnectorCheckout, tools: Sequence[Any]
) -> tuple[ToolVerdict, ...]:
    """One verdict per preset tool, from the server's ``tools/list`` entries."""
    by_name: dict[str, list[Any]] = {}
    for tool in tools:
        by_name.setdefault(tool_name(tool), []).append(tool)
    return tuple(
        _verdict(checkout, tool, by_name.get(tool, [])) for tool in checkout.tools
    )
