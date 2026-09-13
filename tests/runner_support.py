"""Doubles and builders shared by the connector-sync runner tests."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
from fleet_fixtures import (
    ARCHIVEBOX_CONNECTORS,
    ARCHIVEBOX_ROOT,
    FRESHRSS_CONNECTORS,
    FRESHRSS_READING_LIST,
    FRESHRSS_ROOT,
)

from agent_connector_sdk.artifacts.prompts import PromptArtifactKind
from agent_connector_sdk.artifacts.resources import ResourceArtifactKind
from agent_connector_sdk.artifacts.skills import SkillArtifactKind
from agent_connector_sdk.artifacts.tools import ToolArtifactKind
from agent_connector_sdk.contracts import (
    ContentPack,
    IngestionReceipt,
    PackImportReceipt,
    RecordBatch,
)
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.checkpoint_store import CheckpointStore
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.ports.sink import SinkReadiness
from agent_connector_sdk.runner.checkpoints import JsonFileCheckpointStore
from agent_connector_sdk.runner.descriptors import (
    ConnectorDescriptor,
    EndpointSpec,
    RunnerSettings,
)
from agent_connector_sdk.runner.endpoints import EndpointFactory
from agent_connector_sdk.runner.errors import RunnerConfigurationError
from agent_connector_sdk.runner.services import RunnerServices
from agent_connector_sdk.runner.supervisor import ConnectorSyncRunner
from agent_connector_sdk.testing.sinks import InMemorySink
from agent_connector_sdk.transports.mcp import McpTransport

KINDS: tuple[ArtifactKind, ...] = (
    ToolArtifactKind(),
    SkillArtifactKind(),
    PromptArtifactKind(),
    ResourceArtifactKind(),
)
FAST = RunnerSettings(
    max_concurrency=2,
    backoff_initial_seconds=0.01,
    backoff_max_seconds=0.05,
    registry_refresh_seconds=0.05,
)
UNUSED_URL = EndpointSpec(url="https://connector.example.invalid/mcp")


def freshrss_descriptor(**overrides: Any) -> ConnectorDescriptor:
    """The freshrss-agent fixture package, synced on reading-list updates."""
    values: dict[str, Any] = {
        "connector": "freshrss-agent",
        "package_root": FRESHRSS_ROOT,
        "connectors_dir": FRESHRSS_CONNECTORS,
        "endpoint": UNUSED_URL,
        "data_resources": {FRESHRSS_READING_LIST: ("freshrss",)},
        "interval_seconds": 3600.0,
    }
    return ConnectorDescriptor.model_validate({**values, **overrides})


def archivebox_descriptor(**overrides: Any) -> ConnectorDescriptor:
    """The archivebox-api fixture package."""
    values: dict[str, Any] = {
        "connector": "archivebox-api",
        "package_root": ARCHIVEBOX_ROOT,
        "connectors_dir": ARCHIVEBOX_CONNECTORS,
        "endpoint": UNUSED_URL,
        "interval_seconds": 3600.0,
    }
    return ConnectorDescriptor.model_validate({**values, **overrides})


class ListRegistry:
    """A registry whose connectors a test changes while the runner runs."""

    def __init__(self, *descriptors: ConnectorDescriptor) -> None:
        self.descriptors = list(descriptors)
        self.broken = False

    async def connectors(self) -> tuple[ConnectorDescriptor, ...]:
        """The current descriptors, or a registry failure."""
        if self.broken:
            raise RunnerConfigurationError("registry unavailable")
        return tuple(self.descriptors)


class RecordingSink:
    """Counts calls into an ``InMemorySink``; can crash one submit before commit."""

    def __init__(self, inner: InMemorySink | None = None, crash_on: int = 0) -> None:
        self.inner = inner or InMemorySink()
        self.imports = 0
        self.submits = 0
        self._crash_on = crash_on

    async def submit(self, batch: RecordBatch) -> IngestionReceipt:
        """Commit through the in-memory sink unless this is the crashing call."""
        self.submits += 1
        if self.submits == self._crash_on:
            raise RuntimeError("simulated crash before the sink committed")
        return await self.inner.submit(batch)

    async def import_pack(self, pack: ContentPack) -> PackImportReceipt:
        """Import through the in-memory sink."""
        self.imports += 1
        return await self.inner.import_pack(pack)

    async def readiness(self) -> SinkReadiness:
        """Delegate to the wrapped in-memory sink."""
        return await self.inner.readiness()

    def record_ids(self, connector: str) -> set[str]:
        """Every committed record id of ``connector``."""
        return {
            record.record_id
            for batch in self.inner.batches.values()
            if batch.connector == connector
            for record in batch.records
        }


def in_process(servers: dict[str, object]) -> EndpointFactory:
    """An endpoint factory reaching fixture servers in this process."""

    def build(descriptor: ConnectorDescriptor) -> TransportEndpoint:
        return TransportEndpoint(in_process=servers[descriptor.connector])

    return build


def services(
    sink: object, store: CheckpointStore, endpoints: EndpointFactory, **overrides: Any
) -> RunnerServices:
    """Runner services over the MCP transport and the four artifact kinds."""
    values: dict[str, Any] = {
        "transport": McpTransport(),
        "sink": sink,
        "store": store,
        "kinds": KINDS,
        "endpoints": endpoints,
        "settings": FAST,
    }
    return RunnerServices(**{**values, **overrides})


def freshrss_runner(
    sink: object, state: Path, server: object, **descriptor: Any
) -> ConnectorSyncRunner:
    """A runner serving one freshrss-agent fixture server."""
    return ConnectorSyncRunner(
        ListRegistry(freshrss_descriptor(**descriptor)),
        services(
            sink, JsonFileCheckpointStore(state), in_process({"freshrss-agent": server})
        ),
    )


async def eventually(predicate: Callable[[], bool], timeout: float = 15.0) -> None:
    """Wait until ``predicate`` holds."""
    with anyio.fail_after(timeout):
        while not predicate():
            await anyio.sleep(0.02)


def logged(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, Any]]:
    """The structured fields of every captured runner record named ``event``."""
    fields = (getattr(record, "structured", {}) for record in caplog.records)
    return [field for field in fields if field.get("event") == event]


def capture_runner_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Capture runner logs at INFO."""
    caplog.set_level(logging.INFO, logger="agent_connector_sdk.runner")
