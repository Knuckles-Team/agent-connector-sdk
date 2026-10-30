"""Metadata primitives shared by the connector identity readers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

CONNECTOR_ENTRY_POINT_GROUP = "scion_sdk.connector"


class ConnectorIdentityError(ValueError):
    """A connector declares no fleet name, several, or an invalid one."""


def distribution_version(distribution: str) -> str:
    """Return the installed version of ``distribution`` from package metadata.

    This is the one place a version is read. A package spells its version once,
    in ``pyproject.toml``; ``__version__``, the server version and the health
    report all come from here (SCION-CONNECTOR-CONTROL-R071.2).

    Raises:
        ConnectorIdentityError: the distribution is not installed.
    """
    try:
        return version(distribution)
    except PackageNotFoundError as exc:
        raise ConnectorIdentityError(
            f"distribution {distribution!r} is not installed; install it "
            "(editable installs included) so its metadata carries the version"
        ) from exc


def _entry_point_group(document: dict[str, Any]) -> dict[str, Any]:
    """The connector entry-point table of a parsed ``pyproject.toml``."""
    group: dict[str, Any] = (
        document.get("project", {})
        .get("entry-points", {})
        .get(CONNECTOR_ENTRY_POINT_GROUP, {})
    )
    return group
