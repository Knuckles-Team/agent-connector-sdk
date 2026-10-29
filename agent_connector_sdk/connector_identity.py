"""A connector's one declared identity: its fleet name.

The fleet name (for example ``searxng-mcp``) is the name arbora onboards the
connector under and the name epistemic-graph files its content pack, manifest
and ingest under. It is declared once, in package metadata, as the single
entry point of the ``agent_connector_sdk.connector`` group::

    [project.entry-points."agent_connector_sdk.connector"]
    searxng-mcp = "searxng_mcp"

The entry-point name is the fleet name; the value is the connector's
top-level package. :class:`~agent_connector_sdk.mcp.content.ConnectorContent`,
:class:`~agent_connector_sdk.ingest.model.IngestBinding` and the served
``connector://resources`` declaration all resolve the name from here, so a connector
passes no name literal of its own.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, entry_points, version
from pathlib import Path

__all__ = [
    "CONNECTOR_ENTRY_POINT_GROUP",
    "ConnectorIdentityError",
    "ConnectorPoint",
    "connector_distribution",
    "connector_name",
    "connector_point",
    "connector_version",
    "declared_connector_name",
    "distribution_version",
]

CONNECTOR_ENTRY_POINT_GROUP = "agent_connector_sdk.connector"
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ConnectorIdentityError(ValueError):
    """A connector declares no fleet name, several, or an invalid one."""


def _checked(name: str, where: str) -> str:
    if not _NAME.fullmatch(name):
        raise ConnectorIdentityError(f"{where}: invalid connector name {name!r}")
    return name


def _top_level(package: str) -> str:
    return package.split(".", 1)[0]


def connector_name(package: str) -> str:
    """Return the installed fleet name declared for ``package``.

    ``package`` is the connector's module name; ``__name__`` of any module in
    it works. Exactly one ``agent_connector_sdk.connector`` entry point must
    point at its top-level package.
    """
    top = _top_level(package)
    names = sorted(
        {
            point.name
            for point in entry_points(group=CONNECTOR_ENTRY_POINT_GROUP)
            if _top_level(point.value.split(":", 1)[0].strip()) == top
        }
    )
    if not names:
        source = _source_checkout_name(top)
        if source is not None:
            return source
    if len(names) != 1:
        raise ConnectorIdentityError(
            f"package {top!r} must declare exactly one "
            f"{CONNECTOR_ENTRY_POINT_GROUP} entry point; found {names or 'none'}"
        )
    return _checked(names[0], top)


def _source_checkout_name(top: str) -> str | None:
    """The declaration of an uninstalled source checkout, read from its pyproject.

    A package imported from a checkout on ``sys.path`` (a test run, a scaffold
    smoke) has no installed entry points; its ``pyproject.toml`` sits in the
    directory above the package and holds the same declaration.
    """
    spec = importlib.util.find_spec(top)
    if spec is None or not spec.submodule_search_locations:
        return None
    for location in spec.submodule_search_locations:
        pyproject = Path(location).parent / "pyproject.toml"
        if pyproject.is_file():
            name = declared_connector_name(pyproject)
            if name is not None:
                return name
    return None


def declared_connector_name(pyproject: Path) -> str | None:
    """Return the fleet name a ``pyproject.toml`` declares, without installing it.

    Returns ``None`` when the file declares no connector entry point; raises
    :class:`ConnectorIdentityError` when it declares more than one. Gate
    tools and the pipelines name gate read the identity through this.
    """
    document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    group = (
        document.get("project", {})
        .get("entry-points", {})
        .get(CONNECTOR_ENTRY_POINT_GROUP, {})
    )
    if not group:
        return None
    if len(group) != 1:
        raise ConnectorIdentityError(
            f"{pyproject}: declares {len(group)} connector names; exactly one allowed"
        )
    return _checked(next(iter(group)), str(pyproject))


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


@dataclass(frozen=True)
class ConnectorPoint:
    """One resolved ``agent_connector_sdk.connector`` declaration.

    Attributes:
        name: The fleet name (entry-point name).
        package: The connector's top-level package.
        attribute: The ``Connector`` attribute named after ``:`` in the value,
            or ``None`` for a bare package value.
        distribution: The installed distribution that declares it, or the
            ``[project].name`` of a source checkout.
        pyproject: The checkout ``pyproject.toml`` for an uninstalled source
            checkout, else ``None``.
    """

    name: str
    package: str
    attribute: str | None
    distribution: str
    pyproject: Path | None = None


def _split_value(value: str) -> tuple[str, str | None]:
    module, _, attribute = value.partition(":")
    return module.strip(), (attribute.strip() or None)


def connector_point(package: str) -> ConnectorPoint:
    """Resolve the one connector declaration for ``package``.

    Reads the installed entry point; an uninstalled source checkout falls back
    to the ``pyproject.toml`` beside its package.

    Raises:
        ConnectorIdentityError: zero or several declarations, or an invalid name.
    """
    top = _top_level(package)
    points = [
        point
        for point in entry_points(group=CONNECTOR_ENTRY_POINT_GROUP)
        if _top_level(_split_value(point.value)[0]) == top
    ]
    if len(points) == 1:
        point = points[0]
        module, attribute = _split_value(point.value)
        dist = point.dist.name if point.dist is not None else top
        return ConnectorPoint(
            _checked(point.name, top), _top_level(module), attribute, dist
        )
    if not points:
        checkout = _checkout_point(top)
        if checkout is not None:
            return checkout
    raise ConnectorIdentityError(
        f"package {top!r} must declare exactly one "
        f"{CONNECTOR_ENTRY_POINT_GROUP} entry point; "
        f"found {sorted({p.name for p in points}) or 'none'}"
    )


def _checkout_point(top: str) -> ConnectorPoint | None:
    spec = importlib.util.find_spec(top)
    if spec is None or not spec.submodule_search_locations:
        return None
    for location in spec.submodule_search_locations:
        pyproject = Path(location).parent / "pyproject.toml"
        if not pyproject.is_file():
            continue
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        group = (
            document.get("project", {})
            .get("entry-points", {})
            .get(CONNECTOR_ENTRY_POINT_GROUP, {})
        )
        if len(group) == 1:
            name, value = next(iter(group.items()))
            module, attribute = _split_value(str(value))
            dist = str(document.get("project", {}).get("name") or top)
            return ConnectorPoint(
                _checked(name, str(pyproject)),
                _top_level(module),
                attribute,
                dist,
                pyproject,
            )
    return None


def connector_distribution(package: str) -> str:
    """The distribution name that ships ``package``'s connector declaration."""
    return connector_point(package).distribution


def connector_version(package: str) -> str:
    """The connector's version, read from package metadata only."""
    point = connector_point(package)
    try:
        return distribution_version(point.distribution)
    except ConnectorIdentityError:
        if point.pyproject is None:
            raise
        project = tomllib.loads(point.pyproject.read_text(encoding="utf-8"))["project"]
        declared = project.get("version")
        if not declared:
            raise
        return str(declared)
