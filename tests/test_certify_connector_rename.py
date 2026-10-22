"""SDK-CONNECTOR-CONTROL-R072: ``--write`` regenerates fingerprints after a rename."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from certify_support import LIVE, checkout_copy, server_command

from agent_connector_sdk.certify.checkout import load_checkout
from agent_connector_sdk.certify.cli import main
from agent_connector_sdk.certify.pins import render_fingerprints
from agent_connector_sdk.manifest.loader import ManifestError

pytestmark = pytest.mark.spec("SDK-CONNECTOR-CONTROL-R072")


def _rename_fingerprints(root: Path, old: str) -> Path:
    path = root / "connectors" / "tool_schema_fingerprints.json"
    path.write_text(render_fingerprints(old, {"demo_reader": LIVE}), encoding="utf-8")
    return path


def test_check_refuses_and_write_repairs_a_stale_fingerprint_name(
    tmp_path: Path,
) -> None:
    root = checkout_copy(tmp_path, LIVE)
    path = _rename_fingerprints(root, "demo-old-name")
    with pytest.raises(ManifestError, match="connector does not match"):
        load_checkout(root)
    assert main([str(root), "--check", *server_command()]) == 2
    assert main([str(root), "--write", *server_command()]) == 0
    manifest_connector = load_checkout(root).connector
    assert (
        json.loads(path.read_text(encoding="utf-8"))["connector"] == manifest_connector
    )
    assert main([str(root), "--check", *server_command()]) == 0
