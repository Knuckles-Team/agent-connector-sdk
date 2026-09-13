"""Certify one connector checkout against its live MCP server."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent_connector_sdk.certify.checkout import ConnectorCheckout
from agent_connector_sdk.certify.listing import ToolListingError, list_server_tools
from agent_connector_sdk.certify.verdicts import PinStatus, ToolVerdict, tool_verdicts
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.ports.transport import Transport

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

    @property
    def passed(self) -> bool:
        """Whether every preset tool is listed and every pin matches."""
        return (
            self.listed
            and bool(self.verdicts)
            and all(verdict.status is PinStatus.MATCH for verdict in self.verdicts)
        )

    def document(self) -> dict[str, Any]:
        """A JSON-compatible rendering (pins and fingerprints only, no endpoints)."""
        return {
            "connector": self.connector,
            "server": self.server,
            "listed": self.listed,
            "reason": self.reason,
            "server_name": self.server_name,
            "server_version": self.server_version,
            "passed": self.passed,
            "tools": [
                {
                    "tool": verdict.tool,
                    "presets": list(verdict.presets),
                    "status": verdict.status.value,
                    "live": verdict.live,
                    "pins": dict(verdict.pins),
                    "output_schema_sha256": verdict.output_schema_sha256,
                    "defect": verdict.defect,
                }
                for verdict in self.verdicts
            ],
        }


async def certify_connector(
    checkout: ConnectorCheckout,
    transport: Transport,
    endpoint: TransportEndpoint,
    *,
    timeout_seconds: float,
) -> CertificationReport:
    """List the server's tools and compare every preset tool's pins."""
    try:
        listing = await list_server_tools(
            transport, endpoint, timeout_seconds=timeout_seconds
        )
    except ToolListingError as exc:
        _logger.warning("connector %s: %s", checkout.connector, exc)
        return CertificationReport(
            connector=checkout.connector,
            server=checkout.server,
            listed=False,
            reason=f"{exc}; {UNLISTED_DEFECT}",
        )
    return CertificationReport(
        connector=checkout.connector,
        server=checkout.server,
        listed=True,
        server_name=listing.server_name,
        server_version=listing.server_version,
        verdicts=tool_verdicts(checkout, listing.tools),
    )
