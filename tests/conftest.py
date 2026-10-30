"""Shared fixtures: the in-process fixture connector and session factories."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import pytest
from fixture_server import (
    CONNECTOR,
    PACKAGE_ROOT,
    build_malformed_server,
    build_reader_server,
)

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.manifest.model import ResourceSpec, SchemaMapping, SyncSpec
from agent_connector_sdk.ports.session import McpSession, TransportEndpoint
from agent_connector_sdk.testing.results import SessionFactory
from agent_connector_sdk.transports.mcp import McpTransport


def _factory(build: Callable[[], object]) -> SessionFactory:
    def open_session() -> AbstractAsyncContextManager[McpSession]:
        return McpTransport().session(TransportEndpoint(in_process=build()))

    return open_session


@pytest.fixture
def sessions() -> SessionFactory:
    """Fresh sessions to the well-formed fixture connector."""
    return _factory(build_reader_server)


@pytest.fixture
def malformed_sessions() -> SessionFactory:
    """Fresh sessions to a connector whose records are malformed."""
    return _factory(build_malformed_server)


@pytest.fixture
def package_root() -> Path:
    """The fixture connector package directory."""
    return PACKAGE_ROOT


DEMO_PRESET: dict[str, object] = {
    "action": "stream_contents",
    "cursor_param": "continuation",
    "cursor_path": "continuation",
    "doc_type": "demo_item",
    "id_field": "id",
    "pagination": "cursor",
    "params": {"count": 2},
    "params_style": "json",
    "records_path": "items",
    "server": "demo-mcp",
    "text_field": "text",
    "title_field": "title",
    "tool": "demo_reader",
    "type_field": "kind",
    "updated_field": "published",
    "updated_since_param": "newer_than",
}


@pytest.fixture
def adapter() -> McpToolSourceAdapter:
    """The ``mcp_tool`` adapter for the fixture connector's declared source."""
    spec = SyncSpec(
        preset="demo", server="demo-mcp", tool="demo_reader", raw=DEMO_PRESET
    )
    return McpToolSourceAdapter.from_sync_spec(
        spec,
        connector=CONNECTOR,
        mapping_reference=f"connector:{CONNECTOR}",
        schema_mappings={"DemoItem": SchemaMapping(ontology_class="Document")},
        resources=[
            ResourceSpec(name="DemoItem", label="Demo Item", id_prefix="demoitem")
        ],
    )


@pytest.fixture(autouse=True)
def isolated_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep temporary repositories independent of the invoking Git hook.

    Autouse: a pre-push hook exports GIT_DIR and friends, and any test that
    shells out to git would otherwise write the real checkout's config
    (a fixture identity leaked into the shared scion-sdk config this way).
    """
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
