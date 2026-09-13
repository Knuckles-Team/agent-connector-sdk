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
    tool_fingerprint,
    tool_name,
)
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


def _verdict(
    checkout: ConnectorCheckout, tool: str, matches: Sequence[Any]
) -> ToolVerdict:
    if len(matches) != 1:
        state = "does not list" if not matches else "lists more than once"
        return _unavailable(checkout, tool, f"the server {state} tool {tool!r}")
    try:
        live = tool_fingerprint(matches[0])
    except ToolSchemaContractError as exc:
        _logger.warning("tool %r cannot be certified: %s", tool, exc)
        return _unavailable(checkout, tool, str(exc))
    pins = pin_locations(checkout, tool)
    return ToolVerdict(
        tool=tool,
        presets=checkout.presets_for(tool),
        pins=pins,
        status=_status(tool, live, list(pins.values())),
        live=live,
        output_schema_sha256=output_schema_digest(matches[0]),
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
