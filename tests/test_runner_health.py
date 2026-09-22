"""The runner health surface: heartbeat liveness, readiness, the HTTP listener."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, NoReturn

import anyio
import pytest
from runner_support import (
    ListRegistry,
    freshrss_descriptor,
    pack_authority_unexpected,
    services,
)

from agent_connector_sdk.auth.oidc import ClientCredentialsConfig
from agent_connector_sdk.credentials.resolver import EnvironmentCredentialResolver
from agent_connector_sdk.ports.sink import Sink, SinkReadiness
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
from agent_connector_sdk.runner.sink_probe import probe_sink_readiness, sink_reason
from agent_connector_sdk.runner.supervisor import ConnectorSyncRunner
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.sinks import InMemorySink
from agent_connector_sdk.transports.mcp import McpTransport


def _health(
    *,
    sink: Sink | None = None,
    liveness_window_seconds: float = 30.0,
    sink_timeout_seconds: float = 5.0,
    clock: Callable[[], float] = time.monotonic,
) -> RunnerHealth:
    return RunnerHealth(
        sink=sink if sink is not None else InMemorySink(),
        liveness_window_seconds=liveness_window_seconds,
        sink_timeout_seconds=sink_timeout_seconds,
        clock=clock,
    )


class _NotReadySink:
    """A ``Sink`` double that is never ready, for a chosen reason."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def submit(self, batch: object) -> object:
        raise NotImplementedError

    async def source_status(self, connector: str, stream: str) -> object:
        raise NotImplementedError

    async def import_pack(self, pack: object) -> object:
        raise NotImplementedError

    async def readiness(self) -> SinkReadiness:
        return SinkReadiness(ready=False, reason=self._reason)


class _HangingSink:
    """A ``Sink`` double whose ``readiness()`` blocks on an event forever.

    Models a sink whose readiness check makes a network call that never
    returns -- the block is a real ``anyio.Event`` the coroutine is suspended
    on, not a sleep the test hopes outlasts a race.
    """

    def __init__(self, gate: anyio.Event) -> None:
        self._gate = gate

    async def submit(self, batch: object) -> object:
        raise NotImplementedError

    async def source_status(self, connector: str, stream: str) -> object:
        raise NotImplementedError

    async def import_pack(self, pack: object) -> object:
        raise NotImplementedError

    async def readiness(self) -> SinkReadiness:
        return await self._never_ready()

    async def _never_ready(self) -> NoReturn:
        # The gate is never set, so this coroutine never resumes in a passing
        # run; if it ever does, that is a real bug (the timeout stopped
        # bounding the wait), so it fails loudly rather than falling through
        # to a dead `return` a coverage tool would otherwise have to ignore.
        await self._gate.wait()
        raise AssertionError("hanging sink resumed")


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


async def _until_ready(
    get_report: Callable[[], Awaitable[HealthReport]], timeout: float = 5.0
) -> None:
    with anyio.fail_after(timeout):
        while (await get_report()).status != 200:
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


async def test_readiness_reflects_sink_usability() -> None:
    graph = _health(sink=EpistemicGraphSink(object(), pack_authority_unexpected))
    graph.sync_registry(())
    report = await graph.readiness()
    assert (report.status, report.body["reasons"]) == (200, [])

    memory = _health(sink=InMemorySink())
    memory.sync_registry(())
    report = await memory.readiness()
    assert (report.status, report.body["reasons"]) == (200, [])


async def test_epistemic_graph_sink_reports_its_reason() -> None:
    state = await EpistemicGraphSink(object(), pack_authority_unexpected).readiness()
    assert state == SinkReadiness(ready=True)


async def test_readiness_names_a_not_ready_sinks_reason() -> None:
    health = _health(sink=_NotReadySink("database connection refused"))
    health.sync_registry(())
    report = await health.readiness()
    assert report.status == 503
    assert "database connection refused" in report.body["reasons"]


async def test_readiness_503_within_the_timeout_when_the_sink_hangs() -> None:
    gate = anyio.Event()  # never set: the sink's readiness() hangs forever
    health = _health(sink=_HangingSink(gate), sink_timeout_seconds=0.05)
    health.sync_registry(())
    with anyio.fail_after(5.0):  # generous outer bound; a real block still 503s
        report = await health.readiness()
    assert report.status == 503
    assert any("timed out" in reason for reason in report.body["reasons"])


async def test_probe_sink_readiness_passes_through_and_bounds_a_hang() -> None:
    passthrough = await probe_sink_readiness(InMemorySink(), timeout_seconds=5.0)
    assert passthrough == SinkReadiness(ready=True)

    gate = anyio.Event()  # never set: the hanging sink's readiness() never returns
    timed_out = await probe_sink_readiness(_HangingSink(gate), timeout_seconds=0.05)
    assert not timed_out.ready
    assert "timed out" in sink_reason(timed_out)


def test_sink_reason_defaults_when_a_sink_leaves_it_unset() -> None:
    assert sink_reason(SinkReadiness(ready=False)) == "sink not ready"
    assert sink_reason(SinkReadiness(ready=False, reason="boom")) == "boom"


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
        CredentialEndpoints(EnvironmentCredentialResolver()),
        health=health,
    )
    runner = ConnectorSyncRunner(
        ListRegistry(freshrss_descriptor(endpoint=endpoint)), built
    )
    assert await runner.run_once() == {"freshrss-agent": False}

    report = await health.readiness()
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
        CredentialEndpoints(EnvironmentCredentialResolver()),
        health=health,
    )
    runner = ConnectorSyncRunner(ListRegistry(freshrss_descriptor()), built)
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(runner.run_forever)
        await _until_ready(health.readiness)
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


async def test_note_functions_update_a_real_health_object() -> None:
    health = _health(liveness_window_seconds=30.0)
    note_registry_loaded(health, ("freshrss-agent",))
    note_credentials(health, "freshrss-agent", ok=False, error="boom")
    detail = (await health.readiness()).body["connectors"]["freshrss-agent"]
    assert (detail["credentials_ok"], detail["credential_error"]) == (False, "boom")

    note_cycle_success(health, "freshrss-agent")
    detail = (await health.readiness()).body["connectors"]["freshrss-agent"]
    assert detail["consecutive_failures"] == 0

    note_cycle_failure(health, "freshrss-agent", next_retry_seconds=2.5)
    detail = (await health.readiness()).body["connectors"]["freshrss-agent"]
    assert (detail["consecutive_failures"], detail["next_retry_seconds"]) == (1, 2.5)

    note_heartbeat(health)
    assert health.liveness().ok


# ── Endpoint resolution ──────────────────────────────────────────────────


async def test_resolve_endpoint_records_success(tmp_path: Path) -> None:
    health = _health()
    built = services(
        InMemorySink(),
        CredentialEndpoints(EnvironmentCredentialResolver()),
        transport=McpTransport(),
        health=health,
    )
    endpoint = await resolve_endpoint(built, freshrss_descriptor())
    assert endpoint.url == "https://connector.example.invalid/mcp"
    detail = (await health.readiness()).body["connectors"]["freshrss-agent"]
    assert detail["credentials_ok"] is True


async def _endpoint_failure_detail(
    tmp_path: Path, endpoint_spec: EndpointSpec
) -> dict[str, Any]:
    health = _health()
    built = services(
        InMemorySink(),
        CredentialEndpoints(EnvironmentCredentialResolver()),
        transport=McpTransport(),
        health=health,
    )
    with pytest.raises(CredentialResolutionError):
        await resolve_endpoint(built, freshrss_descriptor(endpoint=endpoint_spec))
    detail = (await health.readiness()).body["connectors"]["freshrss-agent"]
    assert detail["credentials_ok"] is False
    return detail


async def test_resolve_endpoint_records_failure_without_the_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CONNECTOR_SYNC_TEST_TOKEN", raising=False)
    endpoint_spec = EndpointSpec(
        url="https://freshrss.example.invalid/mcp",
        bearer_token="env://CONNECTOR_SYNC_TEST_TOKEN",
    )
    detail = await _endpoint_failure_detail(tmp_path, endpoint_spec)
    assert "CONNECTOR_SYNC_TEST_TOKEN" not in detail["credential_error"]


async def test_resolve_endpoint_reports_an_unresolvable_oidc_client_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same choke point (resolve_endpoint -> CredentialEndpoints.__call__) as
    # the bearer_token case above -- there is one endpoint/credential
    # resolution path, so a connector configured for OIDC client-credentials
    # instead of a static bearer token is proven by the same wrapper. A
    # token_url (rather than an issuer) skips OIDC discovery entirely, so
    # this never makes a network call: it fails resolving client_secret_ref,
    # before any token request would be attempted.
    monkeypatch.delenv("CONNECTOR_SYNC_TEST_OIDC_SECRET", raising=False)
    endpoint_spec = EndpointSpec(
        url="https://freshrss.example.invalid/mcp",
        client_credentials=ClientCredentialsConfig(
            token_url="https://oidc.example.invalid/token",
            client_id="connector-sync",
            client_secret_ref="env://CONNECTOR_SYNC_TEST_OIDC_SECRET",
        ),
    )
    detail = await _endpoint_failure_detail(tmp_path, endpoint_spec)
    assert "freshrss-agent" in detail["credential_error"]
    assert "CONNECTOR_SYNC_TEST_OIDC_SECRET" not in detail["credential_error"]


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
