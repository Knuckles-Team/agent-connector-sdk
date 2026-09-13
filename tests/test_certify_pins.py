"""connector-certify: fingerprint canonicalization, checkouts, verdicts and pin writing."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from certify_support import DRIFTED, EMPTY, LIVE, checkout_copy, live_tools
from fixture_server import PACKAGE_ROOT, build_reader_server

from agent_connector_sdk.certify.checkout import (
    ConnectorCheckout,
    find_connectors_dir,
    load_checkout,
)
from agent_connector_sdk.certify.fingerprints import (
    EmptyToolSchemaError,
    is_empty_schema_pin,
    output_schema_digest,
    tool_fingerprint,
    tool_name,
)
from agent_connector_sdk.certify.pins import (
    PinWriteError,
    render_fingerprints,
    rewrite_manifest_pins,
    write_certified_pins,
)
from agent_connector_sdk.certify.verdicts import (
    PinStatus,
    ToolVerdict,
    pin_locations,
    tool_verdicts,
)
from agent_connector_sdk.manifest.loader import (
    ManifestError,
    require_valid_connector_package,
)
from agent_connector_sdk.manifest.tool_schema import (
    ToolSchemaContractError,
    compatibility_fingerprint,
    legacy_empty_schema_fingerprint,
)

COMPACT = (
    '{"name":"t","inputSchema":{"type":"object","properties":{"b":{"type":"string"},'
    '"a":{"type":"integer","description":"A"}},"required":["b","a"]}}'
)
SPACED = """
{ "inputSchema" : { "required" : [ "a" , "b" ],
    "properties" : { "a" : { "title" : "A", "default" : 3, "type" : "integer" },
                     "b" : { "type" : "string" } },
    "type" : "object" },
  "name" : "t" }
"""


def test_canonicalization_ignores_order_whitespace_and_presentation() -> None:
    compact, spaced = json.loads(COMPACT), json.loads(SPACED)
    canonical = {
        "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
        "required": ["a", "b"],
        "type": "object",
    }
    assert tool_fingerprint(compact) == tool_fingerprint(spaced)
    assert tool_fingerprint(spaced) == compatibility_fingerprint("t", canonical)
    retyped = json.loads(COMPACT)
    retyped["inputSchema"]["properties"]["a"]["type"] = "string"
    renamed = {**compact, "name": "u"}
    digests = {tool_fingerprint(item) for item in (compact, retyped, renamed)}
    assert len(digests) == 3
    assert tool_name(spaced) == "t" and tool_name({}) == ""

    output = {
        **compact,
        "outputSchema": {
            "type": "object",
            "properties": {"result": {"type": "string"}},
        },
    }
    output_presentation = json.loads(json.dumps(output))
    output_presentation["outputSchema"]["title"] = "Presentation only"
    changed_output = json.loads(json.dumps(output))
    changed_output["outputSchema"]["properties"]["result"]["type"] = "integer"
    assert tool_fingerprint(output) == tool_fingerprint(output_presentation)
    assert tool_fingerprint(output) != tool_fingerprint(changed_output)


def test_empty_and_nameless_schemas_are_refused() -> None:
    with pytest.raises(EmptyToolSchemaError, match="empty input schema"):
        tool_fingerprint({"name": "t", "inputSchema": {}})
    with pytest.raises(EmptyToolSchemaError):
        tool_fingerprint({"name": "t"})
    with pytest.raises(ToolSchemaContractError, match="no name"):
        tool_fingerprint({"inputSchema": {"type": "object"}})
    assert is_empty_schema_pin("t", compatibility_fingerprint("t", {}).upper())
    assert is_empty_schema_pin("t", legacy_empty_schema_fingerprint("t"))
    assert not is_empty_schema_pin("t", tool_fingerprint(json.loads(COMPACT)))


async def test_server_side_tools_are_refused_and_client_tools_certify() -> None:
    server_side = (await build_reader_server(with_content=False).list_tools())[0]
    # The agent-utilities certifier hashed this object and got the empty schema.
    with pytest.raises(EmptyToolSchemaError):
        tool_fingerprint(server_side)
    (client_side,) = await live_tools()
    wire = client_side.model_dump(by_alias=True, exclude_none=True)
    assert tool_fingerprint(client_side) == tool_fingerprint(wire) == LIVE
    assert output_schema_digest(client_side) == output_schema_digest(wire) != ""
    assert output_schema_digest({"name": "t"}) == ""


def test_load_checkout_in_both_layouts(tmp_path: Path) -> None:
    checkout = load_checkout(PACKAGE_ROOT)
    assert isinstance(checkout, ConnectorCheckout)
    assert (checkout.connector, checkout.server) == ("demo-agent", "demo-mcp")
    assert checkout.tools == ("demo_reader",)
    assert checkout.presets_for("demo_reader") == ("demo",)
    assert checkout.fingerprints_path.parent == find_connectors_dir(PACKAGE_ROOT)
    assert checkout.manifest_path == PACKAGE_ROOT / "connector_manifest.yml"
    assert pin_locations(checkout, "demo_reader") == {
        "tool_schema_fingerprints.json": LIVE,
        "connector_manifest.yml#demo": LIVE,
    }
    nested = tmp_path / "fleet"
    shutil.copytree(PACKAGE_ROOT, nested)
    (nested / "demo_agent").mkdir()
    (nested / "connectors").rename(nested / "demo_agent" / "connectors")
    (nested / "demo_agent" / "connectors" / "tool_schema_fingerprints.json").unlink()
    assert find_connectors_dir(nested) == nested / "demo_agent" / "connectors"
    assert load_checkout(nested).tool_pins == {}


def test_load_checkout_rejects_bad_checkouts(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="exactly one"):
        find_connectors_dir(tmp_path)
    root = checkout_copy(tmp_path)
    presets = root / "connectors" / "mcp_source_presets.json"
    document = json.loads(presets.read_text(encoding="utf-8"))
    document["other"] = {**document["demo"], "server": "other-mcp"}
    presets.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ManifestError, match="exactly one MCP server"):
        load_checkout(root)


@pytest.mark.parametrize(
    ("pin", "status"),
    [
        (LIVE, PinStatus.MATCH),
        (DRIFTED, PinStatus.DRIFT),
        (EMPTY, PinStatus.EMPTY_PIN),
        ("", PinStatus.UNPINNED),
    ],
)
async def test_verdict_status(tmp_path: Path, pin: str, status: PinStatus) -> None:
    checkout = load_checkout(checkout_copy(tmp_path, pin))
    (verdict,) = tool_verdicts(checkout, await live_tools())
    assert (verdict.status, verdict.live, verdict.presets) == (status, LIVE, ("demo",))
    assert verdict.output_schema_sha256 and not verdict.defect


async def test_unavailable_tools_have_defects() -> None:
    checkout = load_checkout(PACKAGE_ROOT)
    listed = await live_tools()
    cases = {
        "does not list": [],
        "more than once": listed * 2,
        "empty input schema": [{"name": "demo_reader", "inputSchema": {}}],
    }
    for defect, tools in cases.items():
        (verdict,) = tool_verdicts(checkout, tools)
        assert verdict.status is PinStatus.TOOL_UNAVAILABLE and not verdict.live
        assert defect in verdict.defect

    (live,) = listed
    unconstrained = live.model_dump(by_alias=True, exclude_none=True)
    unconstrained["inputSchema"]["properties"]["action"] = {"type": "string"}
    (verdict,) = tool_verdicts(checkout, [unconstrained])
    assert verdict.status is PinStatus.TOOL_UNAVAILABLE
    assert "does not enumerate actions" in verdict.defect


def test_render_and_rewrite_pins() -> None:
    fixture = PACKAGE_ROOT / "connectors" / "tool_schema_fingerprints.json"
    rendered = render_fingerprints("demo-agent", {"demo_reader": LIVE})
    assert rendered == fixture.read_text(encoding="utf-8")
    text = (
        "connector: x\nsync:\n- preset: a\n  tool: t\n  tool_schema_sha256: 00\n"
        "  raw: {}\n- preset: 'b'\n  tool_schema_sha256:\r\n"
        "provenance:\n  tool_schema_sha256: ff\n"
    )
    expected = text.replace("sha256: 00", "sha256: 11").replace(
        "sha256:\r\n", "sha256: 22\r\n"
    )
    assert rewrite_manifest_pins(text, {"a": "11", "b": "22"}) == expected
    with pytest.raises(PinWriteError, match="'c'"):
        rewrite_manifest_pins(text, {"c": "33"})


async def test_write_replaces_empty_pins_line_by_line(tmp_path: Path) -> None:
    root = checkout_copy(tmp_path, EMPTY)
    checkout = load_checkout(root)
    before = checkout.manifest_path.read_text(encoding="utf-8").splitlines()
    written = write_certified_pins(
        checkout, tool_verdicts(checkout, await live_tools())
    )
    assert written == (checkout.fingerprints_path, checkout.manifest_path)
    after = checkout.manifest_path.read_text(encoding="utf-8").splitlines()
    assert [
        (old, new) for old, new in zip(before, after, strict=True) if old != new
    ] == [(f"  tool_schema_sha256: {EMPTY}", f"  tool_schema_sha256: {LIVE}")]
    require_valid_connector_package(root)
    reloaded = load_checkout(root)
    (verdict,) = tool_verdicts(reloaded, await live_tools())
    assert verdict.status is PinStatus.MATCH


async def test_write_refuses_uncertifiable_pins(tmp_path: Path) -> None:
    checkout = load_checkout(checkout_copy(tmp_path, EMPTY))
    files = (checkout.manifest_path, checkout.fingerprints_path)
    snapshot = [path.read_bytes() for path in files]
    for tools in ([], [{"name": "demo_reader", "inputSchema": {}}]):
        with pytest.raises(PinWriteError, match="refusing"):
            write_certified_pins(checkout, tool_verdicts(checkout, tools))
    forged = ToolVerdict(
        tool="demo_reader",
        presets=("demo",),
        pins={},
        status=PinStatus.MATCH,
        live=EMPTY,
    )
    for verdicts in ((), (forged,)):
        with pytest.raises(PinWriteError, match="refusing"):
            write_certified_pins(checkout, verdicts)
    assert [path.read_bytes() for path in files] == snapshot
