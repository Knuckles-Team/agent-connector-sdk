"""Certify one connector against its live MCP server."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from scion_sdk.certify.checkout import (
    ConnectorCheckout,
    checkout_from_resources,
)
from scion_sdk.certify.fingerprints import tool_name
from scion_sdk.certify.listing import (
    ToolListing,
    ToolListingError,
    list_server_tools,
)
from scion_sdk.certify.read_only_check import ToolFixture
from scion_sdk.certify.verdicts import ToolStatus, ToolVerdict, tool_verdicts
from scion_sdk.manifest.declaration import ContractError
from scion_sdk.manifest.tool_schema import (
    ToolSchemaContractError,
    canonical_input_schema,
)
from scion_sdk.ports.session import TransportEndpoint
from scion_sdk.ports.transport import Transport
from scion_sdk.testing.successor_parity import compare_successor_tools

__all__ = ["CertificationReport", "certify_connector"]

_logger = logging.getLogger(__name__)

#: Why a server that cannot list tools is a connector defect.
UNLISTED_DEFECT = (
    "listing tools must not require real credentials or an upstream connection"
)


@dataclass(frozen=True)
class CertificationReport:
    """The outcome of certifying one connector.

    ``listed`` is ``False`` when the server could not list its tools; ``reason``
    then carries the failure.
    """

    connector: str
    server: str
    listed: bool
    reason: str = ""
    server_name: str = ""
    server_version: str = ""
    verdicts: tuple[ToolVerdict, ...] = ()
    exact_name_check: bool | None = None
    exact_name_reason: str = ""

    @property
    def passed(self) -> bool:
        """Whether every declared preset tool is listed and valid."""
        return (
            self.listed
            and self.exact_name_check is not False
            and bool(self.verdicts)
            and all(verdict.status is ToolStatus.CERTIFIED for verdict in self.verdicts)
        )

    def document(self) -> dict[str, Any]:
        """A JSON-compatible rendering (fingerprints only, no endpoints)."""
        return {
            "connector": self.connector,
            "server": self.server,
            "listed": self.listed,
            "reason": self.reason,
            "server_name": self.server_name,
            "server_version": self.server_version,
            "passed": self.passed,
            "exact_name_check": self.exact_name_check,
            "exact_name_reason": self.exact_name_reason,
            "tools": [
                {
                    "tool": verdict.tool,
                    "presets": list(verdict.presets),
                    "status": verdict.status.value,
                    "live": verdict.live,
                    "output_schema_sha256": verdict.output_schema_sha256,
                    "defect": verdict.defect,
                }
                for verdict in self.verdicts
            ],
        }


async def certify_connector(
    transport: Transport,
    endpoint: TransportEndpoint,
    *,
    timeout_seconds: float,
    predecessor: TransportEndpoint | None = None,
    fixtures: Mapping[str, ToolFixture] | None = None,
) -> CertificationReport:
    """List the server's tools and declaration; check every preset tool live."""
    try:
        listing, checkout, exact = await _certification_inputs(
            transport,
            endpoint,
            timeout_seconds=timeout_seconds,
            predecessor=predecessor,
        )
    except (ToolListingError, ContractError) as exc:
        _logger.warning("connector certification failed: %s", exc)
        return CertificationReport(
            connector="",
            server="",
            listed=False,
            reason=f"{exc}; {UNLISTED_DEFECT}",
        )
    return CertificationReport(
        connector=checkout.connector,
        server=checkout.server,
        listed=True,
        server_name=listing.server_name,
        server_version=listing.server_version,
        verdicts=tool_verdicts(checkout, listing.tools, fixtures=fixtures),
        exact_name_check=exact[0],
        exact_name_reason=exact[1],
    )


async def _certification_inputs(
    transport: Transport,
    endpoint: TransportEndpoint,
    *,
    timeout_seconds: float,
    predecessor: TransportEndpoint | None,
) -> tuple[ToolListing, ConnectorCheckout, tuple[bool | None, str]]:
    listing = await list_server_tools(
        transport, endpoint, timeout_seconds=timeout_seconds
    )
    checkout = checkout_from_resources(listing.resources)
    if predecessor is None:
        return listing, checkout, (None, "")
    old = await list_server_tools(
        transport, predecessor, timeout_seconds=timeout_seconds
    )
    old_checkout = checkout_from_resources(old.resources)
    result, reason = _exact_names(
        checkout.connector,
        listing.tools,
        old_connector=old_checkout.connector,
        old_tools=old.tools,
    )
    return listing, checkout, (result, reason)


def _name_problem(current: list[str], previous: list[str]) -> str | None:
    if not previous or not all(previous) or not all(current):
        return "tool listing has no names"
    if len(set(previous)) != len(previous) or len(set(current)) != len(current):
        return "tool listing contains duplicate names"
    return None


def _dispatch_tools(tools: tuple[Any, ...]) -> list[str] | None:
    """Names of action-dispatch tools, or ``None`` when a schema is invalid."""
    dispatch: list[str] = []
    for tool in tools:
        try:
            schema = canonical_input_schema(tool, include_presentation=False)
        except ToolSchemaContractError:
            return None
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return None
        if "action" in properties:
            dispatch.append(tool_name(tool))
    return dispatch


def _parity_problem(
    previous: list[str], current: list[str], dispatch: list[str]
) -> str | None:
    parity = compare_successor_tools(previous, current, dispatch_tools=dispatch)
    if parity.lost:
        return f"predecessor tool name is missing: {', '.join(parity.lost)}"
    if parity.dispatch_remaining:
        return "successor contains an action-dispatch tool"
    return None


def _exact_names(
    connector: str,
    tools: tuple[Any, ...],
    *,
    old_connector: str,
    old_tools: tuple[Any, ...],
) -> tuple[bool, str]:
    if connector != old_connector:
        return False, "predecessor connector identity differs"
    current = [tool_name(tool) for tool in tools]
    previous = [tool_name(tool) for tool in old_tools]
    problem = _name_problem(current, previous)
    dispatch = None if problem else _dispatch_tools(tools)
    if problem is None and dispatch is None:
        problem = "successor tool schema is invalid"
    if problem is None and dispatch is not None:
        problem = _parity_problem(previous, current, dispatch)
    if problem is not None:
        return False, problem
    return True, "kept or split; per-operation coverage is not checked"
