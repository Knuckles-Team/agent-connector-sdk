"""Write certified pins into a connector checkout.

Two files carry a tool's pin: ``tool_schema_fingerprints.json`` (rendered
whole, in the fleet's format) and each ``sync`` entry's ``tool_schema_sha256``
in ``connector_manifest.yml`` (rewritten line by line, so the rest of the
generated manifest is byte-for-byte unchanged). Nothing is written unless every
preset tool has a live, non-empty fingerprint and the rewritten manifest parses
back to exactly those pins.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from agent_connector_sdk.certify.checkout import ConnectorCheckout
from agent_connector_sdk.certify.fingerprints import is_empty_schema_pin
from agent_connector_sdk.certify.pin_journal import _PinTransactionError
from agent_connector_sdk.certify.transaction import _replace_pin_pair
from agent_connector_sdk.certify.verdicts import ToolVerdict
from agent_connector_sdk.manifest.model import ConnectorManifest
from agent_connector_sdk.manifest.tool_schema import (
    COMPATIBILITY_FINGERPRINT_ALGORITHM,
)

__all__ = [
    "PinWriteError",
    "render_fingerprints",
    "rewrite_manifest_pins",
    "write_certified_pins",
]

_PRESET_LINE = re.compile(r"^- preset: *['\"]?(?P<name>[^'\"\s#]+)['\"]? *$")
_PIN_LINE = re.compile(r"^(?P<lead>  tool_schema_sha256:) *['\"]?[0-9A-Fa-f]*['\"]? *$")


class PinWriteError(RuntimeError):
    """Certified pins could not be written; no file was changed."""


def render_fingerprints(connector: str, tools: Mapping[str, str]) -> str:
    """The ``tool_schema_fingerprints.json`` document for ``tools``."""
    document = {
        "schema_version": "1",
        "connector": connector,
        "algorithm": COMPATIBILITY_FINGERPRINT_ALGORITHM,
        "tools": dict(sorted(tools.items())),
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _preset_of(line: str, current: str) -> str:
    match = _PRESET_LINE.match(line.rstrip("\r\n"))
    if match:
        return match["name"]
    return "" if line[:1].strip() and not line.startswith("- ") else current


def rewrite_manifest_pins(text: str, pins: Mapping[str, str]) -> str:
    """Replace the ``tool_schema_sha256`` line of each ``sync`` preset in ``pins``.

    Raises:
        PinWriteError: a preset in ``pins`` has no ``tool_schema_sha256`` line.
    """
    lines = text.splitlines(keepends=True)
    preset, written = "", set()
    for index, line in enumerate(lines):
        preset = _preset_of(line, preset)
        match = _PIN_LINE.match(line.rstrip("\r\n"))
        if match and preset in pins:
            ending = line[len(line.rstrip("\r\n")) :]
            lines[index] = f"{match['lead']} {pins[preset]}{ending}"
            written.add(preset)
    missing = sorted(set(pins) - written)
    if missing:
        raise PinWriteError(f"manifest has no tool_schema_sha256 line for {missing!r}")
    return "".join(lines)


def _certified(verdicts: Sequence[ToolVerdict]) -> dict[str, str]:
    refused = sorted(
        verdict.tool
        for verdict in verdicts
        if not verdict.live or is_empty_schema_pin(verdict.tool, verdict.live)
    )
    if refused or not verdicts:
        raise PinWriteError(
            f"refusing to write pins: no certifiable live schema for {refused!r}"
        )
    return {verdict.tool: verdict.live for verdict in verdicts}


def _commit_pair(
    checkout: ConnectorCheckout, *, manifest_text: str, fingerprints_text: str
) -> None:
    try:
        _replace_pin_pair(
            checkout.manifest_path,
            checkout.fingerprints_path,
            manifest_text=manifest_text,
            fingerprints_text=fingerprints_text,
        )
    except _PinTransactionError as exc:
        raise PinWriteError(str(exc)) from exc


def write_certified_pins(
    checkout: ConnectorCheckout, verdicts: Sequence[ToolVerdict]
) -> tuple[Path, Path]:
    """Write the live fingerprints of ``verdicts`` into both pin files.

    Raises:
        PinWriteError: a tool has no certifiable live fingerprint, or the
            rewritten manifest does not parse back to the certified pins.
    """
    live = _certified(verdicts)
    wanted = {
        preset: live[verdict.tool] for verdict in verdicts for preset in verdict.presets
    }
    manifest_text = rewrite_manifest_pins(
        checkout.manifest_path.read_text(encoding="utf-8"), wanted
    )
    reparsed = ConnectorManifest.model_validate(yaml.safe_load(manifest_text))
    written = {entry.preset: entry.tool_schema_sha256 for entry in reparsed.sync}
    if any(written.get(preset) != pin for preset, pin in wanted.items()):
        raise PinWriteError("rewritten manifest does not carry the certified pins")
    _commit_pair(
        checkout,
        manifest_text=manifest_text,
        fingerprints_text=render_fingerprints(checkout.connector, live),
    )
    return checkout.fingerprints_path, checkout.manifest_path
