"""Shared fixtures: the in-process fixture connector and session factories."""

from __future__ import annotations

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
from agent_connector_sdk.manifest.loader import require_valid_connector_package
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


@pytest.fixture
def adapter() -> McpToolSourceAdapter:
    """The ``mcp_tool`` adapter built from the fixture manifest's sync entry."""
    manifest = require_valid_connector_package(PACKAGE_ROOT)
    return McpToolSourceAdapter.from_sync_spec(manifest.sync[0], connector=CONNECTOR)
