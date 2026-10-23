"""Certify one connector against its live MCP server."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent_connector_sdk.certify.checkout import checkout_from_resources
from agent_connector_sdk.certify.listing import ToolListingError, list_server_tools
from agent_connector_sdk.certify.verdicts import ToolStatus, ToolVerdict, tool_verdicts
from agent_connector_sdk.manifest.declaration import ContractError
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
        """Whether every declared preset tool is listed and valid."""
        return (
            self.listed
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
) -> CertificationReport:
    """List the server's tools and declaration; check every preset tool live."""
    try:
        listing = await list_server_tools(
            transport, endpoint, timeout_seconds=timeout_seconds
        )
        checkout = checkout_from_resources(listing.resources)
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
        verdicts=tool_verdicts(checkout, listing.tools),
    )
