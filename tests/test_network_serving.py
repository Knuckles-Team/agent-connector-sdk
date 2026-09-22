"""The SDK-owned network boundary used by connectors and GraphOS."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from agent_connector_sdk.mcp.exposure import NetworkExposureError, is_loopback_host
from agent_connector_sdk.mcp.network import (
    NetworkServingConfig,
    build_network_serving_config,
)
from agent_connector_sdk.mcp.parser import create_mcp_parser
from agent_connector_sdk.mcp.server import create_mcp_server


def _args(*argv: str) -> argparse.Namespace:
    return create_mcp_parser().parse_args(list(argv))


def _terminated_config(**overrides: object) -> NetworkServingConfig:
    values: dict[str, object] = {
        "transport": "streamable-http",
        "host": "0.0.0.0",
        "port": 8000,
        "auth_type": "jwt",
        "allowed_hosts": ("svc.example.invalid",),
        "allowed_origins": ("https://console.example.invalid",),
        "tls_terminated": True,
        "trusted_proxy_cidrs": ("10.0.0.0/8",),
        "max_request_bytes": 1024,
    }
    values.update(overrides)
    return NetworkServingConfig(**values)  # type: ignore[arg-type]


def test_stdio_has_no_network_boundary() -> None:
    assert build_network_serving_config(_args()) is None


def test_loopback_detection_does_not_resolve_dns() -> None:
    assert is_loopback_host("localhost")
    assert is_loopback_host("[::1]")
    assert not is_loopback_host("10.0.0.1")
    assert not is_loopback_host("service.example.invalid")


def test_loopback_defaults_are_exact_and_bounded() -> None:
    config = build_network_serving_config(
        _args("--transport", "streamable-http", "--port", "9123")
    )
    assert isinstance(config, NetworkServingConfig)
    assert config.allowed_hosts == (
        "127.0.0.1:9123",
        "[::1]:9123",
        "localhost:9123",
        "testserver",
    )
    run = config.fastmcp_run_kwargs()
    assert len(run["middleware"]) == 3
    assert run["uvicorn_config"] == {
        "proxy_headers": False,
        "limit_concurrency": 128,
        "backlog": 256,
        "timeout_keep_alive": 5,
        "timeout_graceful_shutdown": 15,
        "h11_max_incomplete_event_size": 65_536,
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"auth_type": "none"}, "requires authentication"),
        ({"tls_terminated": False, "trusted_proxy_cidrs": ()}, "requires TLS"),
        ({"allowed_hosts": ()}, "requires exact allowed hosts"),
        ({"allowed_hosts": ("*.example.invalid",)}, "invalid name"),
        ({"trusted_proxy_cidrs": ("10.0.0.1/8",)}, "CIDR is invalid"),
        ({"allowed_origins": ("https://console.invalid/path",)}, "exact HTTP"),
        ({"limit_concurrency": 0}, "outside the safe range"),
        ({"backlog": 65_536}, "outside the safe range"),
        ({"timeout_keep_alive": 0}, "outside the safe range"),
        ({"timeout_graceful_shutdown": 301}, "outside the safe range"),
        ({"request_body_timeout_seconds": 0.5}, "outside the safe range"),
    ],
)
def test_invalid_listener_policy_fails_closed(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(NetworkExposureError, match=message):
        _terminated_config(**overrides)


def test_direct_tls_is_validated_and_rendered(tmp_path: Path) -> None:
    certfile = tmp_path / "server.crt"
    keyfile = tmp_path / "server.key"
    certfile.write_text("certificate", encoding="utf-8")
    keyfile.write_text("key", encoding="utf-8")
    config = _terminated_config(
        tls_terminated=False,
        trusted_proxy_cidrs=(),
        tls_certfile=str(certfile),
        tls_keyfile=str(keyfile),
    )
    uvicorn_config = config.fastmcp_run_kwargs()["uvicorn_config"]
    assert uvicorn_config["ssl_certfile"] == str(certfile)
    assert uvicorn_config["ssl_keyfile"] == str(keyfile)

    with pytest.raises(NetworkExposureError, match="both certificate and key"):
        _terminated_config(
            tls_terminated=False,
            trusted_proxy_cidrs=(),
            tls_certfile=str(certfile),
        )


def test_environment_resource_bounds_are_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_MAX_CONNECTIONS", "0")
    with pytest.raises(NetworkExposureError, match="MCP_MAX_CONNECTIONS"):
        build_network_serving_config(_args("--transport", "streamable-http"))

    monkeypatch.setenv("MCP_MAX_CONNECTIONS", "64")
    monkeypatch.setenv("MCP_LISTEN_BACKLOG", "512")
    monkeypatch.setenv("MCP_KEEPALIVE_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("MCP_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", "21")
    monkeypatch.setenv("MCP_REQUEST_BODY_TIMEOUT_SECONDS", "12.5")
    config = build_network_serving_config(_args("--transport", "streamable-http"))
    assert config is not None
    assert (
        config.limit_concurrency,
        config.backlog,
        config.timeout_keep_alive,
        config.timeout_graceful_shutdown,
        config.request_body_timeout_seconds,
    ) == (64, 512, 7, 21, 12.5)


async def _body(request: Request) -> JSONResponse:
    body = await request.body()
    return JSONResponse({"size": len(body)})


async def _websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.close()


def _network_app(config: NetworkServingConfig) -> Starlette:
    run = config.fastmcp_run_kwargs()
    return Starlette(
        routes=[
            Route("/tool", _body, methods=["POST"]),
            WebSocketRoute("/events", _websocket),
        ],
        middleware=run["middleware"],
    )


def test_live_boundary_enforces_peer_host_origin_and_body() -> None:
    app = _network_app(_terminated_config())
    with TestClient(
        app,
        base_url="http://svc.example.invalid",
        client=("10.1.2.3", 40_000),
    ) as client:
        accepted = client.post(
            "/tool",
            content=b"x" * 1024,
            headers={"origin": "https://console.example.invalid"},
        )
        assert accepted.status_code == 200 and accepted.json() == {"size": 1024}
        assert (
            client.post("/tool", headers={"host": "other.invalid"}).status_code == 400
        )
        assert (
            client.post(
                "/tool", headers={"origin": "https://other.example.invalid"}
            ).status_code
            == 403
        )
        assert client.post("/tool", content=b"x" * 1025).status_code == 413
        with (
            pytest.raises(WebSocketDisconnect) as rejected,
            client.websocket_connect(
                "/events", headers={"origin": "https://other.example.invalid"}
            ),
        ):
            pass
        assert rejected.value.code == 4403

    with TestClient(
        app,
        base_url="http://svc.example.invalid",
        client=("198.51.100.3", 40_000),
    ) as untrusted:
        assert untrusted.post("/tool").status_code == 403


def test_factory_invokes_network_contract_before_building_server() -> None:
    with pytest.raises(SystemExit) as failure:
        create_mcp_server(
            "demo",
            version="1",
            command_args=[
                "--transport",
                "streamable-http",
                "--max-request-bytes",
                "100",
            ],
        )
    assert failure.value.code == 1
