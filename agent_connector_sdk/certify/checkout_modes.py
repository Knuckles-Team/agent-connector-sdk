"""Resolve the certification view for sync and tool-contract-only checkouts."""

from __future__ import annotations

from pathlib import Path

from agent_connector_sdk.manifest.loader import (
    FINGERPRINTS_FILE_NAME,
    PRESETS_FILE_NAME,
    ManifestError,
    load_tool_presets,
)
from agent_connector_sdk.manifest.model import ConnectorManifest
from agent_connector_sdk.manifest.presets import ToolPreset


def _presets_and_server(
    root: Path,
    directory: Path,
    manifest: ConnectorManifest,
    *,
    contract_only: bool,
) -> tuple[dict[str, ToolPreset], str]:
    """Return one server identity and reject mixed sync/catalog layouts."""
    if contract_only:
        preset_files = (
            directory / PRESETS_FILE_NAME,
            *root.glob(f"*/connectors/{PRESETS_FILE_NAME}"),
        )
        if manifest.sync or any(path.exists() for path in preset_files):
            raise ManifestError(
                "tool-contract-only requires no sync entries or presets"
            )
        if any(root.glob(f"*/connectors/{FINGERPRINTS_FILE_NAME}")):
            raise ManifestError(
                "tool-contract-only requires the root connectors pin file"
            )
        return {}, manifest.connector
    presets = load_tool_presets(directory / PRESETS_FILE_NAME)
    servers = {preset.server for preset in presets.values()}
    if len(servers) != 1:
        raise ManifestError(
            "the presets of one connector must name exactly one MCP server"
        )
    return presets, servers.pop()
