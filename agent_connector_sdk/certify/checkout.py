"""A connector checkout: its sync presets and the pins certification checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_connector_sdk.manifest.loader import (
    FINGERPRINTS_FILE_NAME,
    MANIFEST_FILE_NAME,
    PRESETS_FILE_NAME,
    ManifestError,
    load_manifest,
    load_tool_presets,
    load_tool_schema_fingerprints,
)
from agent_connector_sdk.manifest.presets import ToolPreset

__all__ = ["ConnectorCheckout", "find_connectors_dir", "load_checkout"]


@dataclass(frozen=True)
class ConnectorCheckout:
    """The certification view of one connector package.

    ``tool_pins`` are the ``tool_schema_fingerprints.json`` entries;
    ``manifest_pins`` map each manifest ``sync`` preset to its
    ``tool_schema_sha256`` (``""`` when unset).
    """

    root: Path
    connectors_dir: Path
    connector: str
    server: str
    presets: Mapping[str, ToolPreset]
    tool_pins: Mapping[str, str]
    manifest_pins: Mapping[str, str]

    @property
    def manifest_path(self) -> Path:
        """``<root>/connector_manifest.yml``."""
        return self.root / MANIFEST_FILE_NAME

    @property
    def fingerprints_path(self) -> Path:
        """``<connectors_dir>/tool_schema_fingerprints.json``."""
        return self.connectors_dir / FINGERPRINTS_FILE_NAME

    @property
    def tools(self) -> tuple[str, ...]:
        """The tools the presets extract through, sorted and unique."""
        return tuple(sorted({preset.tool for preset in self.presets.values()}))

    def presets_for(self, tool: str) -> tuple[str, ...]:
        """The presets that extract through ``tool``."""
        return tuple(
            sorted(name for name, preset in self.presets.items() if preset.tool == tool)
        )


def find_connectors_dir(root: Path) -> Path:
    """``<root>/connectors``, else the one ``<root>/*/connectors`` holding presets.

    Raises:
        ManifestError: the checkout has no presets, or more than one set.
    """
    direct = root / "connectors"
    if (direct / PRESETS_FILE_NAME).is_file():
        return direct
    found = sorted(root.glob(f"*/connectors/{PRESETS_FILE_NAME}"))
    if len(found) != 1:
        raise ManifestError(
            f"a connector checkout needs exactly one connectors/{PRESETS_FILE_NAME}; "
            f"found {len(found)}"
        )
    return found[0].parent


def load_checkout(root: Path) -> ConnectorCheckout:
    """Load a connector checkout for certification.

    Raises:
        ManifestError: a package file is missing or malformed, or the presets do
            not name exactly one MCP server.
    """
    manifest = load_manifest(root / MANIFEST_FILE_NAME)
    directory = find_connectors_dir(root)
    presets = load_tool_presets(directory / PRESETS_FILE_NAME)
    servers = {preset.server for preset in presets.values()}
    if len(servers) != 1:
        raise ManifestError(
            "the presets of one connector must name exactly one MCP server"
        )
    fingerprints = directory / FINGERPRINTS_FILE_NAME
    tool_pins = (
        load_tool_schema_fingerprints(fingerprints).tools
        if fingerprints.is_file()
        else {}
    )
    return ConnectorCheckout(
        root=root,
        connectors_dir=directory,
        connector=manifest.connector,
        server=servers.pop(),
        presets=presets,
        tool_pins=dict(tool_pins),
        manifest_pins={
            entry.preset: entry.tool_schema_sha256 or "" for entry in manifest.sync
        },
    )
