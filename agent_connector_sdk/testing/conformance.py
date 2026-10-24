"""Connector conformance checks, derived from the declared connector.

Each check takes the :class:`~agent_connector_sdk.connector.ResolvedConnector`
and raises ``ConformanceFailure`` (an ``AssertionError``) on a violation. The pytest plugin
(:mod:`agent_connector_sdk.testing.plugin`) runs them for any repository whose
``pyproject.toml`` declares an ``agent_connector_sdk.connector`` entry point, so
a connector repository copies no conformance test (SDK-QUALITY-RELEASE-R005.1).
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_connector_sdk.connector import ResolvedConnector, build_server
from agent_connector_sdk.connector_identity import (
    CONNECTOR_ENTRY_POINT_GROUP,
    connector_name,
    distribution_version,
)
from agent_connector_sdk.testing.ontology_rollup import orphan_classes

__all__ = [
    "CHECKS",
    "REMOVED_PROVIDER_GROUPS",
    "Check",
    "ConformanceFailure",
    "run_check",
]

#: Entry-point groups the convention replaces; a connector declares none.
REMOVED_PROVIDER_GROUPS = (
    "agent_connector_sdk.skill_providers",
    "agent_connector_sdk.ontology_providers",
    "agent_connector_sdk.source_connector_providers",
)
_ROW = "SDK-QUALITY-RELEASE-R005.1"


class ConformanceFailure(AssertionError):
    """A connector violates a conformance property."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ConformanceFailure(message)


@dataclass(frozen=True)
class Check:
    """One generated conformance test."""

    name: str
    spec: str
    run: Callable[[ResolvedConnector], None]


def _python_files(resolved: ResolvedConnector) -> list[Path]:
    return sorted(resolved.dirs.root.glob("*.py"))


def _trees(resolved: ResolvedConnector) -> list[tuple[Path, ast.Module]]:
    return [
        (p, ast.parse(p.read_text(encoding="utf-8"))) for p in _python_files(resolved)
    ]


def _pyproject(resolved: ResolvedConnector) -> dict[str, Any]:
    path = resolved.dirs.root.parent / "pyproject.toml"
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


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


def check_fleet_name(resolved: ResolvedConnector) -> None:
    """The fleet name is declared once and every literal in the package matches it."""
    _require(
        connector_name(resolved.package) == resolved.name,
        "identity differs from the declaration",
    )
    group = (
        _pyproject(resolved)
        .get("project", {})
        .get("entry-points", {})
        .get(CONNECTOR_ENTRY_POINT_GROUP)
    )
    if group is not None:
        _require(list(group) == [resolved.name], f"declares {list(group)}")
    for path, tree in _trees(resolved):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if func not in {"IngestBinding", "ConnectorContent"}:
                continue
            for keyword in node.keywords:
                if keyword.arg == "connector" and isinstance(
                    keyword.value, ast.Constant
                ):
                    _require(
                        keyword.value.value == resolved.name,
                        f"{path.name} spells connector {keyword.value.value!r}",
                    )


def check_version_from_metadata(resolved: ResolvedConnector) -> None:
    """The version comes from package metadata and no module spells its own."""
    _require(
        resolved.version == distribution_version(resolved.distribution),
        "version differs from metadata",
    )
    for path, tree in _trees(resolved):
        for node in ast.walk(tree):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            value = getattr(node, "value", None)
            if (
                any(getattr(t, "id", "") == "__version__" for t in targets)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                raise ConformanceFailure(
                    f"{path.name} spells __version__; read metadata"
                )
    module = importlib.import_module(resolved.package)
    declared = getattr(module, "__version__", None)
    _require(declared in (None, resolved.version), f"__version__ {declared!r} differs")


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
    routes = {
        getattr(r, "path", "")
        for r in getattr(
            mcp, "_additional_http_routes", getattr(mcp, "_custom_routes", [])
        )
    }
    _require("/health" in routes or not routes, f"no /health route in {routes}")
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
    from agent_connector_sdk.ingest.live_declaration import (
        build_declaration,
        load_declaration,
        load_sources_module,
    )
    from agent_connector_sdk.mcp.tool_surface import registered_tools

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
    for item in _trees(resolved):
        names = {n.name for n in ast.walk(item[1]) if isinstance(n, ast.FunctionDef)}
        if item[0].name == "connector_sources.py":
            _require("declaration" not in names, "declaration() belongs to the SDK")


def check_ontology_rollup(resolved: ResolvedConnector) -> None:
    """Every ontology class reaches the epistemic-graph core namespace."""
    for path in sorted(resolved.dirs.ontology.glob("*.ttl")):
        orphans = orphan_classes(path)
        _require(not orphans, f"{path.name}: orphan classes {sorted(orphans)}")


def check_kg_ingest(resolved: ResolvedConnector) -> None:
    """The ingest module imports and binds under the fleet name."""
    if importlib.util.find_spec(f"{resolved.package}.kg_ingest") is None:
        return
    from agent_connector_sdk.ingest import IngestBinding

    module = importlib.import_module(f"{resolved.package}.kg_ingest")
    for value in vars(module).values():
        if isinstance(value, IngestBinding):
            _require(value.connector == resolved.name, value.connector)


def check_one_entry_point(resolved: ResolvedConnector) -> None:
    """Content is found by convention: no provider entry points are declared."""
    declared = _pyproject(resolved).get("project", {}).get("entry-points", {})
    stale = [g for g in REMOVED_PROVIDER_GROUPS if g in declared]
    _require(
        not stale,
        f"remove entry-point groups {stale}; the SDK finds content by convention",
    )


CHECKS: tuple[Check, ...] = (
    Check("fleet_name", _ROW, check_fleet_name),
    Check("version_from_metadata", _ROW, check_version_from_metadata),
    Check("startup", _ROW, check_startup),
    Check("content_surfaces", _ROW, check_content_surfaces),
    Check("prompts_served", _ROW, check_prompts_served),
    Check("connector_sources", _ROW, check_connector_sources),
    Check("ontology_rollup", _ROW, check_ontology_rollup),
    Check("kg_ingest", _ROW, check_kg_ingest),
    Check("one_entry_point", _ROW, check_one_entry_point),
)


def run_check(name: str, resolved: ResolvedConnector) -> None:
    """Run the named check."""
    next(c for c in CHECKS if c.name == name).run(resolved)
