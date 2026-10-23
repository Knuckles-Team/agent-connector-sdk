"""The fingerprint, listing and certification surface that reads a live server."""

from __future__ import annotations

from types import SimpleNamespace

import anyio
import pytest
from fastmcp import FastMCP

from agent_connector_sdk.certify.certification import CertificationReport
from agent_connector_sdk.certify.checkout import ConnectorCheckout
from agent_connector_sdk.certify.cli import (
    PLACEHOLDER_VALUE,
    build_endpoint,
    parse_arguments,
)
from agent_connector_sdk.certify.fingerprints import (
    EmptyToolSchemaError,
    is_empty_schema_pin,
    output_schema_digest,
    tool_fingerprint,
)
from agent_connector_sdk.certify.listing import (
    ToolListing,
    ToolListingError,
    list_server_tools,
)
from agent_connector_sdk.certify.verdicts import ToolStatus, ToolVerdict
from agent_connector_sdk.manifest.live_contract import (
    LiveToolContract,
    validate_live_tool_contract,
)
from agent_connector_sdk.manifest.model import ResourceRelation
from agent_connector_sdk.manifest.tool_schema import (
    COMPATIBILITY_FINGERPRINT_ALGORITHM,
    ToolSchemaContractError,
    canonical_input_schema,
    canonical_output_schema,
    compatibility_fingerprint,
    legacy_empty_schema_fingerprint,
    read_field,
    schema_fingerprint,
)
from agent_connector_sdk.signing import canonical
from agent_connector_sdk.transports.mcp import McpTransport

TOOL = SimpleNamespace(
    name="t",
    inputSchema={"type": "object", "properties": {"a": {"type": "string"}}},
    outputSchema=None,
)


def test_fingerprints_are_deterministic_and_refuse_empty_schemas() -> None:
    first = tool_fingerprint(TOOL)
    assert first == tool_fingerprint(TOOL)
    assert first == compatibility_fingerprint(
        "t", canonical_input_schema(TOOL, include_presentation=False), None
    )
    assert first != schema_fingerprint("t", {"type": "object"})
    assert canonical_output_schema(TOOL, include_presentation=False) in (None, {})
    assert len(output_schema_digest(TOOL)) == 64
    assert read_field(TOOL, "name") == "t"
    assert COMPATIBILITY_FINGERPRINT_ALGORITHM
    empty = SimpleNamespace(name="e", inputSchema={})
    with pytest.raises(EmptyToolSchemaError):
        tool_fingerprint(empty)
    assert is_empty_schema_pin("e", compatibility_fingerprint("e", {}))
    assert is_empty_schema_pin("e", legacy_empty_schema_fingerprint("e"))
    with pytest.raises(ToolSchemaContractError):
        tool_fingerprint(SimpleNamespace(name="", inputSchema={"type": "object"}))


def test_live_contract_carries_both_fingerprints() -> None:
    contract = validate_live_tool_contract([TOOL], tool_name="t")
    assert isinstance(contract, LiveToolContract)
    assert contract.compatibility_sha256 == tool_fingerprint(TOOL)


def test_listing_reads_tools_and_declaration() -> None:
    mcp = FastMCP("listed")

    @mcp.tool
    def ping() -> str:
        """Ping."""
        return "pong"

    class _Transport:
        def session(self, endpoint: object):
            from agent_connector_sdk.ports.session import TransportEndpoint

            return McpTransport().session(TransportEndpoint(in_process=mcp))

    async def run() -> None:
        listing = await list_server_tools(_Transport(), None, timeout_seconds=5)  # type: ignore[arg-type]
        assert isinstance(listing, ToolListing)
        assert [t.name for t in listing.tools] == ["ping"]

    # no declaration resource is served here, so listing it fails closed
    with pytest.raises(ToolListingError):
        anyio.run(run)


def test_cli_arguments_and_endpoint() -> None:
    args = parse_arguments(["--placeholder", "TOKEN", "--", "server", "--flag"])
    assert args.command == ["server", "--flag"]
    endpoint = build_endpoint(args)
    assert endpoint.env == {"TOKEN": PLACEHOLDER_VALUE}
    assert endpoint.command == "server"


def test_report_and_verdict_documents() -> None:
    verdict = ToolVerdict(
        tool="t", presets=("p",), status=ToolStatus.CERTIFIED, live="abc"
    )
    report = CertificationReport(
        connector="c", server="s", listed=True, verdicts=(verdict,)
    )
    assert report.passed is True
    assert report.document()["tools"][0]["status"] == "certified"
    checkout = ConnectorCheckout(connector="c", server="s", presets={})
    assert checkout.tools == ()


def test_resource_relation_and_canonical_json() -> None:
    relation = ResourceRelation(name="owns", target="Thing")
    assert relation.label == ""
    assert canonical({"b": 1, "a": 2}) == '{"a":2,"b":1}'
