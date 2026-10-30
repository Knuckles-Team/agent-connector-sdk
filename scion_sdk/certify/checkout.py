"""A connector as certification sees it: its declared sync presets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scion_sdk.manifest.declaration import (
    ContractError,
    contract_from_document,
)
from scion_sdk.manifest.presets import ToolPreset

__all__ = ["ConnectorCheckout", "checkout_from_resources"]


@dataclass(frozen=True)
class ConnectorCheckout:
    """The connector's name, its MCP server name and its declared presets."""

    connector: str
    server: str
    presets: Mapping[str, ToolPreset]

    @property
    def tools(self) -> tuple[str, ...]:
        """The tools the presets extract through, sorted and unique."""
        return tuple(sorted({preset.tool for preset in self.presets.values()}))

    def presets_for(self, tool: str) -> tuple[str, ...]:
        """The presets that extract through ``tool``."""
        return tuple(
            sorted(name for name, preset in self.presets.items() if preset.tool == tool)
        )


def checkout_from_resources(text: str) -> ConnectorCheckout:
    """The checkout described by a ``connector://resources`` body.

    Raises:
        ContractError: the body is invalid, declares no preset, or its presets
            do not name exactly one MCP server.
    """
    contract = contract_from_document(text)
    if contract is None:
        raise ContractError("the server declares no sync preset")
    presets = {
        spec.preset: ToolPreset.from_mapping(spec.preset, dict(spec.raw))
        for spec in contract.sync
    }
    servers = {preset.server for preset in presets.values()}
    if len(servers) != 1:
        raise ContractError(
            "the presets of one connector must name exactly one MCP server"
        )
    return ConnectorCheckout(
        connector=contract.connector, server=servers.pop(), presets=presets
    )
