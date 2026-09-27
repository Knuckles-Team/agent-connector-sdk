"""A connector checkout: its sync presets and the pins certification checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_connector_sdk.certify.checkout_modes import _presets_and_server
from agent_connector_sdk.certify.pin_journal import (
    _PinTransactionError,
    _recover_pin_transaction,
)
from agent_connector_sdk.manifest.loader import (
    FINGERPRINTS_FILE_NAME,
    MANIFEST_FILE_NAME,
    PRESETS_FILE_NAME,
    ManifestError,
    ToolSchemaFingerprints,
    load_manifest,
    load_tool_schema_fingerprints,
    validate_connector_package,
)
from agent_connector_sdk.manifest.model import ConnectorManifest
from agent_connector_sdk.manifest.presets import ToolPreset

__all__ = ["ConnectorCheckout", "find_connectors_dir", "load_checkout"]

_VALIDATION_MODE: dict[bool, Literal["sync", "contract_only"]] = {
    True: "contract_only",
    False: "sync",
}


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
    contract_only: bool = False
    pin_algorithm: str = ""

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
        options = (
            tuple(sorted({preset.tool for preset in self.presets.values()})),
            tuple(sorted(self.tool_pins)),
        )
        return options[self.contract_only]

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


def _connectors_dir(root: Path, contract_only: bool) -> Path:
    return root / "connectors" if contract_only else find_connectors_dir(root)


def _recover_pin_files(root: Path, directory: Path) -> None:
    try:
        _recover_pin_transaction(
            root / MANIFEST_FILE_NAME, directory / FINGERPRINTS_FILE_NAME
        )
    except _PinTransactionError as exc:
        raise ManifestError("an interrupted pin update could not be recovered") from exc


def _load_fingerprints(
    manifest_connector: str, directory: Path
) -> ToolSchemaFingerprints:
    path = directory / FINGERPRINTS_FILE_NAME
    if path.is_file():
        return load_tool_schema_fingerprints(path)
    return ToolSchemaFingerprints(connector=manifest_connector, algorithm="", tools={})


def _validate_identity(
    manifest: ConnectorManifest,
    presets: dict[str, ToolPreset],
    fingerprints: ToolSchemaFingerprints,
    *,
    contract_only: bool,
) -> None:
    violations = validate_connector_package(
        manifest,
        presets,
        fingerprints,
        allow_pin_migration=True,
        mode=_VALIDATION_MODE[contract_only],
    )
    if violations:
        raise ManifestError("; ".join(violations))


def load_checkout(root: Path, *, contract_only: bool = False) -> ConnectorCheckout:
    """Load a connector checkout for certification.

    Raises:
        ManifestError: a package file is missing or malformed, or the presets do
            not name exactly one MCP server.
    """
    directory = _connectors_dir(root, contract_only)
    _recover_pin_files(root, directory)
    manifest = load_manifest(root / MANIFEST_FILE_NAME)
    presets, server = _presets_and_server(
        root, directory, manifest, contract_only=contract_only
    )
    fingerprints = _load_fingerprints(manifest.connector, directory)
    _validate_identity(manifest, presets, fingerprints, contract_only=contract_only)
    return ConnectorCheckout(
        root=root,
        connectors_dir=directory,
        connector=manifest.connector,
        server=server,
        presets=presets,
        tool_pins=dict(fingerprints.tools),
        manifest_pins={
            entry.preset: entry.tool_schema_sha256 or "" for entry in manifest.sync
        },
        contract_only=contract_only,
        pin_algorithm=fingerprints.algorithm,
    )
