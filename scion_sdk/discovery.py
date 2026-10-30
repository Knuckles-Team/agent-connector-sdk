"""Entry-point discovery of extensions, with fail-closed activation.

Replaces ``agent_utilities.protocols.source_connectors.registry``. AU's registry
self-registered connector classes with a decorator and discovered them by
importing modules inside AU, so a new source kind meant editing AU. Here an
extension self-registers by declaring a Python entry point in its own
distribution, in one of five groups:

* ``scion_sdk.source_adapters``
* ``scion_sdk.artifact_kinds``
* ``scion_sdk.transports``
* ``scion_sdk.sinks``
* ``scion_sdk.platform_backends``

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

from scion_sdk import __version__

__all__ = [
    "ARTIFACT_KIND_GROUP",
    "EXTENSION_GROUPS",
    "PLATFORM_BACKEND_GROUP",
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

SOURCE_ADAPTER_GROUP = "scion_sdk.source_adapters"
ARTIFACT_KIND_GROUP = "scion_sdk.artifact_kinds"
TRANSPORT_GROUP = "scion_sdk.transports"
SINK_GROUP = "scion_sdk.sinks"
PLATFORM_BACKEND_GROUP = "scion_sdk.platform_backends"
EXTENSION_GROUPS = (
    SOURCE_ADAPTER_GROUP,
    ARTIFACT_KIND_GROUP,
    TRANSPORT_GROUP,
    SINK_GROUP,
    PLATFORM_BACKEND_GROUP,
)

_SDK_DISTRIBUTION = "scion-sdk"


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


def load_extension(
    group: str,
    name: str,
    *,
    policy: ActivationPolicy,
    expected_version: str | None = None,
) -> object:
    """Load exactly the installed entry point authorized by the supplied policy.

    When supplied, ``expected_version`` binds activation to the caller's pinned
    adapter version. The selected entry point's metadata is checked again
    before its code is loaded.
    """
    identity = next(
        (item for item in discover_extensions(group) if item.name == name), None
    )
    if identity is None:
        raise LookupError(f"no extension named {name!r} is declared in {group}")
    candidates = tuple(entry_points(group=group, name=name))
    if len(candidates) != 1 or _identity(group, candidates[0]) != identity:
        raise ExtensionDiscoveryError("extension metadata changed during activation")
    if expected_version is not None and identity.version != expected_version:
        raise ExtensionActivationError(
            "extension version does not match the admitted policy"
        )
    if not policy.authorizes(identity):
        raise ExtensionActivationError(
            f"extension {name!r} in {group} from {identity.distribution} "
            f"{identity.version} is not certified for activation"
        )
    return candidates[0].load()


def sdk_reference_extensions() -> CertifiedExtensions:
    """A policy certifying the reference implementations this SDK version ships."""
    return CertifiedExtensions(
        (identity.group, identity.name, identity.distribution, identity.version)
        for group in EXTENSION_GROUPS
        for identity in discover_extensions(group)
        if identity.distribution == _SDK_DISTRIBUTION
        and identity.version == __version__
    )
