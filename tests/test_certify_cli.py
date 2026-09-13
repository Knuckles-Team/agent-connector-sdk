"""connector-certify: listing through the Transport port and the console script."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx2
import pytest
from certify_support import DRIFTED, EMPTY, LIVE, checkout_copy, server_command
from fixture_server import PACKAGE_ROOT, build_reader_server

import agent_connector_sdk.certify.cli as certify_cli
from agent_connector_sdk.auth.oidc import ClientCredentialsConfig
from agent_connector_sdk.certify.certification import (
    CertificationReport,
    certify_connector,
)
from agent_connector_sdk.certify.checkout import load_checkout
from agent_connector_sdk.certify.cli import (
    PLACEHOLDER_VALUE,
    build_endpoint,
    build_parser,
    main,
    parse_arguments,
)
from agent_connector_sdk.certify.listing import (
    ToolListing,
    ToolListingError,
    list_server_tools,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport

EXITING = TransportEndpoint(command=sys.executable, args=("-c", "raise SystemExit(4)"))


def _in_process() -> TransportEndpoint:
    return TransportEndpoint(in_process=build_reader_server(with_content=False))


async def test_list_server_tools() -> None:
    listing = await list_server_tools(McpTransport(), _in_process(), timeout_seconds=30)
    assert isinstance(listing, ToolListing)
    assert (listing.server_name, listing.server_version) == ("demo-mcp", "1.4.0")
    assert [tool.name for tool in listing.tools] == ["demo_reader"]
    with pytest.raises(ToolListingError, match="did not list its tools"):
        await list_server_tools(McpTransport(), EXITING, timeout_seconds=30)


async def test_list_server_tools_is_bounded_in_time() -> None:
    silent = TransportEndpoint(
        command=sys.executable, args=("-c", "import time; time.sleep(60)")
    )
    with pytest.raises(ToolListingError, match="TimeoutError"):
        await list_server_tools(McpTransport(), silent, timeout_seconds=1)


async def test_certify_connector_reports() -> None:
    checkout = load_checkout(PACKAGE_ROOT)
    report = await certify_connector(
        checkout, McpTransport(), _in_process(), timeout_seconds=30
    )
    assert isinstance(report, CertificationReport) and report.passed
    document = report.document()
    assert (document["server_version"], document["passed"]) == ("1.4.0", True)
    assert document["tools"][0]["status"] == "match"
    assert document["tools"][0]["live"] == LIVE
    unlisted = await certify_connector(
        checkout, McpTransport(), EXITING, timeout_seconds=30
    )
    assert not (unlisted.listed or unlisted.passed)
    assert "must not require real credentials" in unlisted.reason
    assert unlisted.document()["tools"] == []


def test_build_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERTIFY_TEST_TOKEN", "t0ken")
    stdio = build_endpoint(
        parse_arguments(
            [
                "pkg",
                "--check",
                "--placeholder",
                "A",
                "--env",
                "B=env://CERTIFY_TEST_TOKEN",
                "--timeout",
                "5",
                "--",
                "server",
                "--transport",
                "stdio",
                "--",
            ]
        )
    )
    assert (stdio.command, stdio.args, stdio.timeout_seconds) == (
        "server",
        ("--transport", "stdio", "--"),
        5.0,
    )
    assert dict(stdio.env) == {"A": PLACEHOLDER_VALUE, "B": "t0ken"}
    http = build_endpoint(
        parse_arguments(
            [
                "pkg",
                "--write",
                "--url",
                "http://127.0.0.1:9/mcp",
                "--bearer-token",
                "env://CERTIFY_TEST_TOKEN",
            ]
        )
    )
    assert (http.url, http.bearer_token, http.command) == (
        "http://127.0.0.1:9/mcp",
        "t0ken",
        "",
    )
    assert http.args == () and "--" in (build_parser().epilog or "")

    captured: list[ClientCredentialsConfig] = []

    def auth(config: ClientCredentialsConfig) -> httpx2.Auth:
        captured.append(config)
        return httpx2.BasicAuth("client", "credential")

    monkeypatch.setattr(certify_cli, "client_credentials_auth", auth)
    oidc = build_endpoint(
        parse_arguments(
            [
                "pkg",
                "--check",
                "--url",
                "https://connector.example.invalid/mcp",
                "--oidc-token-url",
                "https://identity.example.invalid/token",
                "--oidc-client-id",
                "connector-certify",
                "--oidc-client-secret-ref",
                "openbao://apps/connector-certify#OIDC_CLIENT_SECRET",
                "--oidc-audience",
                "agent-services",
                "--oidc-scope",
                "mcp:tools",
            ]
        )
    )
    assert isinstance(oidc.auth, httpx2.BasicAuth)
    assert captured == [
        ClientCredentialsConfig(
            token_url="https://identity.example.invalid/token",
            client_id="connector-certify",
            client_secret_ref="openbao://apps/connector-certify#OIDC_CLIENT_SECRET",
            audience="agent-services",
            scope="mcp:tools",
        )
    ]
    assert "openbao" not in repr(oidc)
    with pytest.raises(SystemExit):
        parse_arguments(["pkg", "--check", "--write"])


def test_cli_check_passes_on_correct_pins(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    argv = [str(PACKAGE_ROOT), "--check", "--report", str(report)]
    assert main(argv + server_command()) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["passed"] is True


@pytest.mark.parametrize(("pin", "status"), [(DRIFTED, "drift"), (EMPTY, "empty_pin")])
def test_cli_check_fails_on_wrong_pins(tmp_path: Path, pin: str, status: str) -> None:
    root, report = checkout_copy(tmp_path, pin), tmp_path / "report.json"
    argv = [str(root), "--check", "--report", str(report)]
    assert main(argv + server_command()) == 1
    document = json.loads(report.read_text(encoding="utf-8"))
    assert document["tools"][0]["status"] == status and not document["passed"]


def test_cli_write_produces_pins_that_check(tmp_path: Path) -> None:
    root = checkout_copy(tmp_path, EMPTY)
    assert main([str(root), "--write", *server_command()]) == 0
    assert load_checkout(root).tool_pins == {"demo_reader": LIVE}
    assert main([str(root), "--check", *server_command()]) == 0
    unchanged = (root / "connector_manifest.yml").read_bytes()
    assert main([str(root), "--write", *server_command("--without-reader")]) == 1
    assert (root / "connector_manifest.yml").read_bytes() == unchanged


def test_cli_reports_a_server_that_needs_credentials(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    needs = server_command("--require-credential", "DEMO_TOKEN")
    assert main([str(PACKAGE_ROOT), "--check", "--report", str(report), *needs]) == 2
    document = json.loads(report.read_text(encoding="utf-8"))
    assert document["listed"] is False and "credentials" in document["reason"]
    placeholder = ["--placeholder", "DEMO_TOKEN"]
    assert main([str(PACKAGE_ROOT), "--check", *placeholder, *needs]) == 0


def test_cli_cannot_start(tmp_path: Path) -> None:
    assert main([str(tmp_path), "--check", *server_command()]) == 2
    assert main([str(PACKAGE_ROOT), "--check"]) == 2
    bad_env = [str(PACKAGE_ROOT), "--check", "--env", "NOVALUE"]
    assert main(bad_env + server_command()) == 2
