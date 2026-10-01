"""SDK-CONNECTOR-CONTROL-R007: fleet-wide re-certification yields nonempty
schema fingerprints for every declared tool pin across the full connector
set this repository ships -- a passing package count alone is not evidence
that every pin's fingerprint was actually computed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fixture_server import PACKAGE_ROOT, build_reader_server
from fleet_fixtures import (
    ARCHIVEBOX_ROOT,
    FRESHRSS_ROOT,
    FakeArchiveBox,
    FakeFreshRss,
    build_enumerated_archivebox_server,
    build_enumerated_freshrss_server,
)

from agent_connector_sdk.certify.certification import (
    CertificationReport,
    certify_connector,
)
from agent_connector_sdk.certify.checkout import load_checkout
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport

#: Every connector package this repository ships as a certifiable fixture,
#: paired with a live server builder whose contract matches its pinned
#: fingerprints. A real fleet cutover re-certifies external connector
#: repositories the same way, through the same ``certify_connector`` path;
#: this proves the mechanism over every package available here.
_FLEET: tuple[tuple[Path, Callable[[], FastMCP[Any]]], ...] = (
    (PACKAGE_ROOT, lambda: build_reader_server(with_content=False)),
    (ARCHIVEBOX_ROOT, lambda: build_enumerated_archivebox_server(FakeArchiveBox([]))),
    (FRESHRSS_ROOT, lambda: build_enumerated_freshrss_server(FakeFreshRss([]))),
)


async def _certify(
    root: Path, build: Callable[[], FastMCP[Any]]
) -> CertificationReport:
    endpoint = TransportEndpoint(in_process=build())
    return await certify_connector(
        load_checkout(root), McpTransport(), endpoint, timeout_seconds=30
    )


async def test_fleet_wide_recertification_fingerprints_every_pin() -> None:
    reports = [await _certify(root, build) for root, build in _FLEET]
    assert len(reports) == len(_FLEET) == 3
    for report in reports:
        assert report.listed and report.passed, (report.connector, report.reason)
        assert report.verdicts, f"{report.connector} certified no tool pins"
        for verdict in report.verdicts:
            assert verdict.live, (
                f"{report.connector}/{verdict.tool}: empty input schema fingerprint"
            )
            assert verdict.output_schema_sha256, (
                f"{report.connector}/{verdict.tool}: empty output schema fingerprint"
            )


async def test_a_drifted_package_fails_live_contract_comparison_not_silently() -> None:
    """Re-certification is a live comparison, not a static count: a server
    that no longer matches its pinned contract fails, even though the same
    package "exists" and was certifiable before."""
    report = await _certify(
        ARCHIVEBOX_ROOT, lambda: build_enumerated_archivebox_server(FakeArchiveBox([]))
    )
    assert report.passed

    drifted = await certify_connector(
        load_checkout(ARCHIVEBOX_ROOT),
        McpTransport(),
        TransportEndpoint(in_process=FastMCP("ArchiveBox MCP", version="1.0.0")),
        timeout_seconds=30,
    )
    assert not drifted.passed
    assert drifted.verdicts and drifted.verdicts[0].status.value == "tool_unavailable"
