"""pytest plugin generating connector conformance tests from the declaration.

Registered as the ``pytest11`` entry point ``scion_sdk``. When the
repository under test declares an ``scion_sdk.connector`` entry point
in its ``pyproject.toml``, the plugin adds one test per
:data:`~scion_sdk.testing.conformance.CHECKS` item, so the repository
copies none of them (SCION-QUALITY-RELEASE-R005.1). A repository without the
declaration, and a run that names explicit test node ids, get nothing added.
Disable with ``-p no:scion_sdk``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from scion_sdk.connector import ResolvedConnector, resolve_connector
from scion_sdk.connector_identity import CONNECTOR_ENTRY_POINT_GROUP
from scion_sdk.testing.conformance import CHECKS, Check

__all__ = ["ConformanceItem", "declared_package"]


def declared_package(root: Path) -> str | None:
    """The package ``root/pyproject.toml`` declares as the connector, or ``None``."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    group = (
        tomllib.loads(pyproject.read_text(encoding="utf-8"))
        .get("project", {})
        .get("entry-points", {})
        .get(CONNECTOR_ENTRY_POINT_GROUP, {})
    )
    if len(group) != 1:
        return None
    value = str(next(iter(group.values())))
    return value.split(":", 1)[0].strip().split(".", 1)[0]


class ConformanceItem(pytest.Item):
    """One generated conformance test."""

    def __init__(
        self, *, check: Check, resolved: ResolvedConnector, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.check = check
        self.resolved = resolved
        self.add_marker(pytest.mark.spec(check.spec))

    def runtest(self) -> None:
        self.check.run(self.resolved)

    def reportinfo(self) -> tuple[Path, int, str]:
        return self.path, 0, f"connector conformance: {self.check.name}"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "spec(id): requirement the test is bound to")


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    if any("::" in str(arg) for arg in config.args):
        return
    package = declared_package(config.rootpath)
    if package is None:
        return
    resolved = resolve_connector(package)
    pyproject = config.rootpath / "pyproject.toml"
    for check in CHECKS:
        items.append(
            ConformanceItem.from_parent(
                session,
                name=f"connector_conformance::{check.name}",
                check=check,
                resolved=resolved,
                path=pyproject,
            )
        )
