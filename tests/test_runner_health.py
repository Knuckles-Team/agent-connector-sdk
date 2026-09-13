"""The runner health surface: heartbeat liveness, readiness, the HTTP listener."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import anyio
import pytest
from runner_support import ListRegistry, freshrss_descriptor, services

from agent_connector_sdk.credentials.resolver import EnvironmentCredentialResolver
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.runner.checkpoints import JsonFileCheckpointStore
from agent_connector_sdk.runner.credentialed_endpoint import resolve_endpoint
from agent_connector_sdk.runner.descriptors import ConnectorDescriptor, EndpointSpec
from agent_connector_sdk.runner.endpoints import CredentialEndpoints
from agent_connector_sdk.runner.errors import (
    CredentialResolutionError,
    RunnerConfigurationError,
)
from agent_connector_sdk.runner.health_reporting import (
    note_credentials,
    note_cycle_failure,
    note_cycle_success,
    note_heartbeat,
    note_registry_loaded,
)
from agent_connector_sdk.runner.health_server import (
    DEFAULT_HEALTH_HOST,
    HealthServer,
    parse_health_address,
)
from agent_connector_sdk.runner.health_state import (
    ConnectorHealth,
    HealthReport,
    RunnerHealth,
)
from agent_connector_sdk.runner.supervisor import ConnectorSyncRunner
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.sinks import InMemorySink
from agent_connector_sdk.transports.mcp import McpTransport


def _health(
    *,
    sink: Sink | None = None,
    liveness_window_seconds: float = 30.0,
    clock: Callable[[], float] = time.monotonic,
) -> RunnerHealth:
    return RunnerHealth(
        sink=sink if sink is not None else InMemorySink(),
        liveness_window_seconds=liveness_window_seconds,
        clock=clock,
    )


class _NeverConnects:
    """A registry whose ``connectors()`` blocks on an event the test controls.

    Models a wedged scheduler loop deterministically -- the block is a real
    ``anyio.Event`` the loop is suspended on, not a sleep the test hopes is
    long enough.
    """

    def __init__(self, gate: anyio.Event) -> None:
        self._gate = gate

    async def connectors(self) -> tuple[ConnectorDescriptor, ...]:
        await self._gate.wait()
        return ()


async def _until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    with anyio.fail_after(timeout):
        while not predicate():
            await anyio.sleep(0.01)


# ── Liveness ──────────────────────────────────────────────────────────────


def test_liveness_is_ok_at_construction_and_after_a_heartbeat() -> None:
    clock = {"t": 0.0}
    health = _health(liveness_window_seconds=5.0, clock=lambda: clock["t"])
    assert health.liveness().ok

    clock["t"] = 5.1
    report = health.liveness()
    assert not report.ok
    assert report.status == 503
    assert report.body["component"] == "scheduler_loop"

    health.heartbeat()
    assert health.liveness().ok


async def test_liveness_goes_stale_when_the_scheduler_loop_wedges(
    tmp_path: Path,
) -> None:
    gate = anyio.Event()  # never set: the registry read hangs forever
    health = _health(liveness_window_seconds=0.05)
    built = services(
        InMemorySink(),
        JsonFileCheckpointStore(tmp_path),
        CredentialEndpoints(EnvironmentCredentialResolver()),
        health=health,
    )
    runner = ConnectorSyncRunner(_NeverConnects(gate), built)
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(runner.run_forever)
        await _until(lambda: not health.liveness().ok)
        tasks.cancel_scope.cancel()
    assert health.liveness().body["component"] == "scheduler_loop"


# ── Readiness ─────────────────────────────────────────────────────────────


def test_readiness_reflects_sink_usability() -> None:
    stub = _health(sink=EpistemicGraphSink(client=None))
    stub.sync_registry(())
    assert stub.readiness().status == 503
    assert any("sink" in reason for reason in stub.readiness().body["reasons"])

    memory = _health(sink=InMemorySink())
    memory.sync_registry(())
    assert memory.readiness().status == 200
    assert memory.readiness().body["reasons"] == []


async def test_readiness_reports_credential_failure_by_name_without_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CONNECTOR_SYNC_TEST_TOKEN", raising=False)
    endpoint = EndpointSpec(
        url="https://freshrss.example.invalid/mcp",
        bearer_token="env://CONNECTOR_SYNC_TEST_TOKEN",
    )
    health = _health()
    built = services(
        InMemorySink(),
        JsonFileCheckpointStore(tmp_path),
        CredentialEndpoints(EnvironmentCredentialResolver()),
        health=health,
    )
    runner = ConnectorSyncRunner(
        ListRegistry(freshrss_descriptor(endpoint=endpoint)), built
    )
    assert await runner.run_once() == {"freshrss-agent": False}

    report = health.readiness()
    assert report.status == 503
    rendered = json.dumps(report.body)
    assert "freshrss-agent" in rendered
    assert "CONNECTOR_SYNC_TEST_TOKEN" not in rendered
    detail = report.body["connectors"]["freshrss-agent"]
    assert detail["credentials_ok"] is False
    assert "could not be resolved" in detail["credential_error"]


async def test_readiness_true_once_registry_and_credentials_are_proven(
    tmp_path: Path,
) -> None:
    # freshrss_descriptor's default endpoint carries no credential reference,
    # so it resolves trivially even though the session itself later fails
    # against the unreachable URL -- this proves readiness tracks registry
    # load and credential resolution independently of cycle success.
    health = _health()
    built = services(
        InMemorySink(),
        JsonFileCheckpointStore(tmp_path),
        CredentialEndpoints(EnvironmentCredentialResolver()),
        health=health,
    )
    runner = ConnectorSyncRunner(ListRegistry(freshrss_descriptor()), built)
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(runner.run_forever)
        await _until(lambda: health.readiness().status == 200)
        tasks.cancel_scope.cancel()


# ── The data shapes ──────────────────────────────────────────────────────


def test_connector_health_snapshot_has_no_secret_field() -> None:
    entry = ConnectorHealth(
        connector="freshrss-agent",
        last_success_monotonic=10.0,
        consecutive_failures=2,
        next_retry_seconds=5.0,
        credentials_ok=False,
        credential_error="connector 'freshrss-agent' has a credential reference "
        "that could not be resolved",
    )
    snapshot = entry.snapshot(now=15.0)
    assert snapshot == {
        "last_success_seconds_ago": 5.0,
        "consecutive_failures": 2,
        "next_retry_seconds": 5.0,
        "credentials_ok": False,
        "credential_error": entry.credential_error,
    }


def test_health_report_carries_status_and_body() -> None:
    report = HealthReport(ok=True, status=200, body={"status": "ok"})
    assert (report.ok, report.status, report.body) == (True, 200, {"status": "ok"})


# ── The optional-health call sites ─────────────────────────────────────────


def test_note_functions_are_no_ops_without_health_tracking() -> None:
    # None models the tests that build RunnerServices without a health object;
    # every note_* helper must tolerate it silently.
    note_heartbeat(None)
    note_registry_loaded(None, ("freshrss-agent",))
    note_credentials(None, "freshrss-agent", ok=True)
    note_cycle_success(None, "freshrss-agent")
    note_cycle_failure(None, "freshrss-agent", next_retry_seconds=5.0)


def test_note_functions_update_a_real_health_object() -> None:
    health = _health(liveness_window_seconds=30.0)
    note_registry_loaded(health, ("freshrss-agent",))
    note_credentials(health, "freshrss-agent", ok=False, error="boom")
    detail = health.readiness().body["connectors"]["freshrss-agent"]
    assert (detail["credentials_ok"], detail["credential_error"]) == (False, "boom")

    note_cycle_success(health, "freshrss-agent")
    detail = health.readiness().body["connectors"]["freshrss-agent"]
    assert detail["consecutive_failures"] == 0

    note_cycle_failure(health, "freshrss-agent", next_retry_seconds=2.5)
    detail = health.readiness().body["connectors"]["freshrss-agent"]
    assert (detail["consecutive_failures"], detail["next_retry_seconds"]) == (1, 2.5)

    note_heartbeat(health)
    assert health.liveness().ok


# ── Endpoint resolution ──────────────────────────────────────────────────


async def test_resolve_endpoint_records_success(tmp_path: Path) -> None:
    health = _health()
    built = services(
        InMemorySink(),
        JsonFileCheckpointStore(tmp_path),
        CredentialEndpoints(EnvironmentCredentialResolver()),
        transport=McpTransport(),
        health=health,
    )
    endpoint = await resolve_endpoint(built, freshrss_descriptor())
    assert endpoint.url == "https://connector.example.invalid/mcp"
    detail = health.readiness().body["connectors"]["freshrss-agent"]
    assert detail["credentials_ok"] is True


async def test_resolve_endpoint_records_failure_without_the_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CONNECTOR_SYNC_TEST_TOKEN", raising=False)
    endpoint_spec = EndpointSpec(
        url="https://freshrss.example.invalid/mcp",
        bearer_token="env://CONNECTOR_SYNC_TEST_TOKEN",
    )
    health = _health()
    built = services(
        InMemorySink(),
        JsonFileCheckpointStore(tmp_path),
        CredentialEndpoints(EnvironmentCredentialResolver()),
        transport=McpTransport(),
        health=health,
    )
    with pytest.raises(CredentialResolutionError):
        await resolve_endpoint(built, freshrss_descriptor(endpoint=endpoint_spec))
    detail = health.readiness().body["connectors"]["freshrss-agent"]
    assert detail["credentials_ok"] is False
    assert "CONNECTOR_SYNC_TEST_TOKEN" not in detail["credential_error"]


# ── The HTTP listener ────────────────────────────────────────────────────


def test_default_health_host_is_loopback() -> None:
    assert DEFAULT_HEALTH_HOST == "127.0.0.1"


def test_parse_health_address_accepts_port_or_host_port() -> None:
    assert parse_health_address("8765") == ("127.0.0.1", 8765)
    assert parse_health_address(" 0.0.0.0:8765 ") == ("0.0.0.0", 8765)
    with pytest.raises(RunnerConfigurationError):
        parse_health_address("not-an-address")


def test_health_server_binds_loopback_and_refuses_non_loopback_by_default() -> None:
    health = _health()
    with pytest.raises(RunnerConfigurationError):
        HealthServer(health, host="0.0.0.0", port=0)
    allowed = HealthServer(health, host="0.0.0.0", port=0, allow_non_loopback=True)
    allowed.stop()


def test_health_endpoints_serve_liveness_and_readiness_json() -> None:
    health = _health()
    server = HealthServer(health, host="127.0.0.1", port=0)
    server.start()
    try:
        host, port = server.address

        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=5) as resp:
            assert resp.status == 200
            assert json.loads(resp.read())["status"] == "ok"

        with pytest.raises(urllib.error.HTTPError) as ready_error:
            urllib.request.urlopen(f"http://{host}:{port}/health/ready", timeout=5)
        assert ready_error.value.code == 503
        body = json.loads(ready_error.value.read())
        assert body["status"] == "not_ready"

        with pytest.raises(urllib.error.HTTPError) as not_found:
            urllib.request.urlopen(f"http://{host}:{port}/nope", timeout=5)
        assert not_found.value.code == 404
    finally:
        server.stop()
