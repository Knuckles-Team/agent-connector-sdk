"""Static conformance checks over a connector's source, metadata and ontology."""

from __future__ import annotations

import ast
import importlib
import tomllib
from pathlib import Path
from typing import Any

from scion_sdk.connector import ResolvedConnector
from scion_sdk.connector_identity import (
    CONNECTOR_ENTRY_POINT_GROUP,
    connector_name,
    distribution_version,
)

#: Entry-point groups the convention replaces; a connector declares none.
REMOVED_PROVIDER_GROUPS = (
    "scion_sdk.skill_providers",
    "scion_sdk.ontology_providers",
    "scion_sdk.source_connector_providers",
)


class ConformanceFailure(AssertionError):
    """A connector violates a conformance property."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ConformanceFailure(message)


def _python_files(resolved: ResolvedConnector) -> list[Path]:
    return sorted(resolved.dirs.root.glob("*.py"))


def trees(resolved: ResolvedConnector) -> list[tuple[Path, ast.Module]]:
    return [
        (p, ast.parse(p.read_text(encoding="utf-8"))) for p in _python_files(resolved)
    ]


def pyproject(resolved: ResolvedConnector) -> dict[str, Any]:
    path = resolved.dirs.root.parent / "pyproject.toml"
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _check_fleet_name(resolved: ResolvedConnector) -> None:
    """The fleet name is declared once and every literal in the package matches it."""
    _require(
        connector_name(resolved.package) == resolved.name,
        "identity differs from the declaration",
    )
    group = (
        pyproject(resolved)
        .get("project", {})
        .get("entry-points", {})
        .get(CONNECTOR_ENTRY_POINT_GROUP)
    )
    if group is not None:
        _require(list(group) == [resolved.name], f"declares {list(group)}")
    for path, tree in trees(resolved):
        for node in ast.walk(tree):
            _check_literal_connector(path, node, resolved.name)


def _check_literal_connector(path: Path, node: ast.AST, name: str) -> None:
    if not isinstance(node, ast.Call):
        return
    func = getattr(node.func, "id", getattr(node.func, "attr", ""))
    if func not in {"IngestBinding", "ConnectorContent"}:
        return
    for keyword in node.keywords:
        if keyword.arg == "connector" and isinstance(keyword.value, ast.Constant):
            _require(
                keyword.value.value == name,
                f"{path.name} spells connector {keyword.value.value!r}",
            )


def _check_version_from_metadata(resolved: ResolvedConnector) -> None:
    """The version comes from package metadata and no module spells its own."""
    _require(
        resolved.version == distribution_version(resolved.distribution),
        "version differs from metadata",
    )
    for path, tree in trees(resolved):
        for node in ast.walk(tree):
            if _spells_version(node):
                raise ConformanceFailure(
                    f"{path.name} spells __version__; read metadata"
                )
    module = importlib.import_module(resolved.package)
    declared = getattr(module, "__version__", None)
    _require(declared in (None, resolved.version), f"__version__ {declared!r} differs")


def _spells_version(node: ast.AST) -> bool:
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        return False
    value = getattr(node, "value", None)
    return (
        any(getattr(t, "id", "") == "__version__" for t in targets)
        and isinstance(value, ast.Constant)
        and isinstance(value.value, str)
    )
