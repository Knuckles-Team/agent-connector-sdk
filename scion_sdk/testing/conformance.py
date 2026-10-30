"""Connector conformance checks, derived from the declared connector.

Each check takes the :class:`~scion_sdk.connector.ResolvedConnector`
and raises ``ConformanceFailure`` (an ``AssertionError``) on a violation. The pytest plugin
(:mod:`scion_sdk.testing.plugin`) runs them for any repository whose
``pyproject.toml`` declares an ``scion_sdk.connector`` entry point, so
a connector repository copies no conformance test (SCION-QUALITY-RELEASE-R005.1).
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from scion_sdk.connector import ResolvedConnector, build_server
from scion_sdk.testing._conformance_declared import (
    _check_config_mounts,
    _check_one_entry_point,
    _check_ontology_rollup,
)
from scion_sdk.testing._conformance_static import (
    REMOVED_PROVIDER_GROUPS,
    ConformanceFailure,
    _check_fleet_name,
    _check_version_from_metadata,
    _require,
    trees,
)

__all__ = [
    "CHECKS",
    "REMOVED_PROVIDER_GROUPS",
    "Check",
    "ConformanceFailure",
    "run_check",
]

_ROW = "SCION-QUALITY-RELEASE-R005.1"


@dataclass(frozen=True)
class Check:
    """One generated conformance test."""

    name: str
    spec: str
    run: Callable[[ResolvedConnector], None]


def _server(resolved: ResolvedConnector, *args: str) -> Any:
    return build_server(resolved.package, command_args=list(args))[1]


def _listings(resolved: ResolvedConnector) -> tuple[set[str], dict[str, str]]:
    from fastmcp import Client

    async def read() -> tuple[set[str], dict[str, str]]:
        async with Client(_server(resolved)) as client:
            resources = {str(r.uri) for r in await client.list_resources()}
            prompts = {
                p.name: (p.description or "") for p in await client.list_prompts()
            }
            return resources, prompts

    return asyncio.run(read())


def _health_status(mcp: Any) -> int:
    """GET ``/health`` through the server's own ASGI app."""
    from starlette.testclient import TestClient

    with TestClient(mcp.http_app()) as client:
        return client.get("/health").status_code


def check_startup(resolved: ResolvedConnector) -> None:
    """The connector builds over each transport, reports its version and answers health."""
    try:
        _server(resolved, "--help")
    except SystemExit as exit_:
        _require(exit_.code in (0, None), "--help exited non-zero")
    else:  # pragma: no cover - --help always exits
        raise ConformanceFailure("--help did not exit")
    mcp = _server(resolved, "--transport", "stdio")
    _require(
        str(getattr(mcp, "version", resolved.version)) == resolved.version,
        "server version differs from metadata",
    )
    _require(mcp.name == resolved.name, "server name differs from the fleet name")
    _require(_health_status(mcp) == 200, "/health did not answer 200")
    if (resolved.dirs.root / "__main__.py").is_file():
        spec = importlib.util.find_spec(f"{resolved.package}.__main__")
        _require(spec is not None, "module has no spec")


def check_content_surfaces(resolved: ResolvedConnector) -> None:
    """The server lists its packaged skills, ontology and shapes by default."""
    resources, _ = _listings(resolved)
    dirs = resolved.dirs
    if list(dirs.skills.glob("*/SKILL.md")):
        _require(any(u.startswith("skill://") for u in resources), "skills not served")
    for path in dirs.ontology.glob("*.ttl"):
        _require(f"ontology://{resolved.name}/{path.name}" in resources, path.name)
    for path in (dirs.ontology / "shapes").glob("*.ttl"):
        _require(f"shapes://{resolved.name}/{path.name}" in resources, path.name)


def check_prompts_served(resolved: ResolvedConnector) -> None:
    """Every packaged prompt is a native MCP prompt."""
    _, prompts = _listings(resolved)
    for path in resolved.dirs.prompts.glob("*.json"):
        if not path.name.startswith("_"):
            _require(path.stem in prompts, f"prompt {path.stem} not served")


def check_connector_sources(resolved: ResolvedConnector) -> None:
    """Declared sources load as typed data and name tools the server registers."""
    if importlib.util.find_spec(f"{resolved.package}.connector_sources") is None:
        return
    from scion_sdk.ingest.live_declaration import (
        build_declaration,
        load_declaration,
        load_sources_module,
    )
    from scion_sdk.mcp.tool_surface import registered_tools

    declaration = load_declaration(resolved.package)
    _require(
        declaration.connector == resolved.name, "declaration names another connector"
    )
    mcp = _server(resolved)
    build_declaration(
        resolved.name,
        registered_tools(mcp).values(),
        declared=load_sources_module(resolved.dirs.root),
    )
    for item in trees(resolved):
        names = {n.name for n in ast.walk(item[1]) if isinstance(n, ast.FunctionDef)}
        if item[0].name == "connector_sources.py":
            _require("declaration" not in names, "declaration() belongs to the SDK")


def check_kg_ingest(resolved: ResolvedConnector) -> None:
    """The ingest module imports and binds under the fleet name."""
    if importlib.util.find_spec(f"{resolved.package}.kg_ingest") is None:
        return
    from scion_sdk.ingest import IngestBinding

    module = importlib.import_module(f"{resolved.package}.kg_ingest")
    for value in vars(module).values():
        if isinstance(value, IngestBinding):
            _require(value.connector == resolved.name, value.connector)


CHECKS: tuple[Check, ...] = (
    Check("fleet_name", _ROW, _check_fleet_name),
    Check("version_from_metadata", _ROW, _check_version_from_metadata),
    Check("startup", _ROW, check_startup),
    Check("content_surfaces", _ROW, check_content_surfaces),
    Check("prompts_served", _ROW, check_prompts_served),
    Check("connector_sources", _ROW, check_connector_sources),
    Check("ontology_rollup", _ROW, _check_ontology_rollup),
    Check("kg_ingest", _ROW, check_kg_ingest),
    Check("one_entry_point", _ROW, _check_one_entry_point),
    Check("config_mounts", "SCION-CONNECTOR-CONTROL-R019.3", _check_config_mounts),
)


def run_check(name: str, resolved: ResolvedConnector) -> None:
    """Run the named check."""
    next(c for c in CHECKS if c.name == name).run(resolved)
