"""Event feed discovery is composed into the served connector runner."""

from functools import partial

import anyio
import pytest
from fastmcp import FastMCP

from scion_sdk.discovery import CertifiedExtensions, sdk_reference_extensions
from scion_sdk.ingest.live_declaration import source_meta
from scion_sdk.mcp.tool_surface import register_tool_surface
from scion_sdk.ports.session import TransportEndpoint
from scion_sdk.runner import cli
from scion_sdk.runner.descriptors import (
    ConnectorDescriptor,
    EndpointSpec,
    RunnerSettings,
)
from scion_sdk.runner.services import RunnerServices
from scion_sdk.runner.worker import ConnectorWorker
from scion_sdk.testing.sinks import InMemorySink
from scion_sdk.transports.mcp import McpTransport


@pytest.mark.spec("SCION-OBSERVABILITY-FEEDS-R001.4")
async def test_declared_event_feed_reaches_served_worker(tmp_path, monkeypatch):
    server = FastMCP("events")
    calls = []
    event = {
        "tenant_id": "tenant-a",
        "source": "browser",
        "stream": "events",
        "event_kind": "page_view",
        "schema_version": "1",
        "provider_event_id": "1",
        "event_time": "2026-09-30T00:00:00Z",
        "source_observed_time": "2026-09-30T00:00:00Z",
        "ingest_time": "2026-09-30T00:00:00Z",
        "actor_ref": "session",
        "target_ref": "/",
        "visibility_label": "internal",
        "payload": {"signal": "page_view", "page": "/", "session_id": "session"},
    }

    @server.tool(
        meta=source_meta(
            source_id="events",
            record_type="Event",
            id_field="provider_event_id",
            ontology_class="https://example.org/Event",
            feed_kind="rum",
            preset={"records_path": "events"},
        )
    )
    def list_events(params_json: str = "{}") -> dict:
        calls.append(1)
        return {"events": [event], "status": "ok"}

    register_tool_surface(server, service="demo", package_root=tmp_path)
    sink = InMemorySink()
    descriptor = ConnectorDescriptor(
        connector="demo",
        endpoint=EndpointSpec(url="https://example.invalid/mcp"),
        provision=False,
    )
    services = RunnerServices(
        transport=McpTransport(),
        sink=sink,
        kinds=(),
        endpoints=lambda _: TransportEndpoint(in_process=server),
        settings=RunnerSettings(),
        source_adapter_policy=sdk_reference_extensions(),
    )
    config = tmp_path / "runner.yml"
    config.write_text(
        "connectors:\n  - connector: demo\n    endpoint:\n      url: https://example.invalid/mcp\n    provision: false\n"
    )
    monkeypatch.setattr(cli, "default_services", lambda *args, **kwargs: services)
    assert (
        await anyio.to_thread.run_sync(
            partial(cli.main, ["--config", str(config), "--once"])
        )
        == 0
    )
    assert calls == [1]
    status = await sink.source_status("demo", "events")
    assert status.accepted_checkpoint is not None

    denied = RunnerServices(
        transport=McpTransport(),
        sink=InMemorySink(),
        kinds=(),
        endpoints=lambda _: TransportEndpoint(in_process=server),
        settings=RunnerSettings(),
        source_adapter_policy=CertifiedExtensions(()),
    )
    assert not await ConnectorWorker(
        descriptor, denied, anyio.CapacityLimiter(1)
    ).run_once()
    assert calls == [1]
