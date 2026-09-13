"""Entry-point discovery of extensions, with fail-closed activation.

Replaces ``agent_utilities.protocols.source_connectors.registry``. AU's registry
self-registered connector classes with a decorator and discovered them by
importing modules inside AU, so a new source kind meant editing AU. Here an
extension self-registers by declaring a Python entry point in its own
distribution, in one of four groups:

* ``agent_connector_sdk.source_adapters``
* ``agent_connector_sdk.artifact_kinds``
* ``agent_connector_sdk.transports``
* ``agent_connector_sdk.sinks``

AU's certified-bundle governance is kept as an explicit
:class:`ActivationPolicy`: loading an extension requires a policy that
authorizes the exact group, name, distribution and version. There is no
permissive default and no development bypass. Discovery itself also fails
closed: two distributions registering the same name in one group is an error,
not a last-writer-wins overwrite.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Protocol

from agent_connector_sdk._version import __version__

__all__ = [
    "ARTIFACT_KIND_GROUP",
    "EXTENSION_GROUPS",
    "SINK_GROUP",
    "SOURCE_ADAPTER_GROUP",
    "TRANSPORT_GROUP",
    "ActivationPolicy",
    "CertifiedExtensions",
    "ExtensionActivationError",
    "ExtensionDiscoveryError",
    "ExtensionIdentity",
    "discover_extensions",
    "load_extension",
    "sdk_reference_extensions",
]

SOURCE_ADAPTER_GROUP = "agent_connector_sdk.source_adapters"
ARTIFACT_KIND_GROUP = "agent_connector_sdk.artifact_kinds"
TRANSPORT_GROUP = "agent_connector_sdk.transports"
SINK_GROUP = "agent_connector_sdk.sinks"
EXTENSION_GROUPS = (
    SOURCE_ADAPTER_GROUP,
    ARTIFACT_KIND_GROUP,
    TRANSPORT_GROUP,
    SINK_GROUP,
)

_SDK_DISTRIBUTION = "agent-connector-sdk"


class ExtensionDiscoveryError(RuntimeError):
    """Installed extension metadata is ambiguous or unreadable."""


class ExtensionActivationError(PermissionError):
    """An extension is not authorized by the activation policy."""


@dataclass(frozen=True)
class ExtensionIdentity:
    """One declared extension and the distribution that ships it."""

    group: str
    name: str
    distribution: str
    version: str
    target: str


class ActivationPolicy(Protocol):
    """Decides whether a discovered extension may be loaded."""

    def authorizes(self, identity: ExtensionIdentity) -> bool:
        """Return ``True`` only for an extension this policy certifies."""
        ...


class CertifiedExtensions:
    """Authorizes exactly the listed ``(group, name, distribution, version)``."""

    def __init__(self, certified: Iterable[tuple[str, str, str, str]]) -> None:
        self._certified = frozenset(certified)

    def authorizes(self, identity: ExtensionIdentity) -> bool:
        """Membership test on the exact identity tuple."""
        return (
            identity.group,
            identity.name,
            identity.distribution,
            identity.version,
        ) in self._certified


def _identity(group: str, entry_point: EntryPoint) -> ExtensionIdentity:
    distribution = entry_point.dist
    if distribution is None:
        raise ExtensionDiscoveryError(
            f"extension {entry_point.name!r} in {group} has no distribution metadata"
        )
    return ExtensionIdentity(
        group=group,
        name=entry_point.name,
        distribution=distribution.metadata["Name"],
        version=distribution.version,
        target=entry_point.value,
    )


def discover_extensions(group: str) -> tuple[ExtensionIdentity, ...]:
    """List the extensions declared in ``group``, sorted by name.

    Raises:
        ValueError: ``group`` is not one of :data:`EXTENSION_GROUPS`.
        ExtensionDiscoveryError: a name is declared by more than one
            distribution.
    """
    if group not in EXTENSION_GROUPS:
        raise ValueError(f"unknown extension group {group!r}")
    found: dict[str, ExtensionIdentity] = {}
    for entry_point in entry_points(group=group):
        identity = _identity(group, entry_point)
        existing = found.get(identity.name)
        if existing is not None and existing != identity:
            raise ExtensionDiscoveryError(
                f"extension name {identity.name!r} in {group} is declared by both "
                f"{existing.distribution} and {identity.distribution}"
            )
        found[identity.name] = identity
    return tuple(found[name] for name in sorted(found))


def load_extension(group: str, name: str, *, policy: ActivationPolicy) -> object:
    """Load the object an authorized extension entry point names.

    Raises:
        LookupError: no extension named ``name`` is declared in ``group``.
        ExtensionActivationError: the policy does not authorize it.
    """
    for identity in discover_extensions(group):
        if identity.name != name:
            continue
        if not policy.authorizes(identity):
            raise ExtensionActivationError(
                f"extension {name!r} in {group} from {identity.distribution} "
                f"{identity.version} is not certified for activation"
            )
        (entry_point,) = entry_points(group=group, name=name)
        return entry_point.load()
    raise LookupError(f"no extension named {name!r} is declared in {group}")


def sdk_reference_extensions() -> CertifiedExtensions:
    """A policy certifying the reference implementations this SDK version ships."""
    return CertifiedExtensions(
        (identity.group, identity.name, identity.distribution, identity.version)
        for group in EXTENSION_GROUPS
        for identity in discover_extensions(group)
        if identity.distribution == _SDK_DISTRIBUTION
        and identity.version == __version__
    )
