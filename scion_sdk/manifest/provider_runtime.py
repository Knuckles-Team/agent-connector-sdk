"""Selecting a runtime profile for a connector with more than one backend.

Some connectors speak to one of several interchangeable backend
implementations (self-hosted vs. managed, different API generations). Each
backend is described once as a :class:`ProviderRuntimeProfile`; the connector
picks one by a configured provider identifier, and construction fails closed
before any request is attempted when that identifier is missing or unknown.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = [
    "ProviderRuntimeProfile",
    "UnknownProviderRuntimeError",
    "resolve_selected_provider_runtime_profile",
]


@dataclass(frozen=True)
class ProviderRuntimeProfile:
    """One backend implementation a multi-backend connector can select.

    Attributes:
        identifier: The provider identifier a connector is configured with.
        base_url: The backend's API root.
        auth_mode: The authentication scheme this backend expects.
        capabilities: Capability flags this backend's client may rely on.
    """

    identifier: str
    base_url: str
    auth_mode: str
    capabilities: frozenset[str] = field(default_factory=frozenset)


class UnknownProviderRuntimeError(LookupError):
    """The configured provider identifier is missing or not registered."""


def resolve_selected_provider_runtime_profile(
    selected: str | None,
    profiles: Mapping[str, ProviderRuntimeProfile],
) -> ProviderRuntimeProfile:
    """Return the profile ``selected`` names, before any network call.

    Args:
        selected: The connector's configured provider identifier.
        profiles: Every registered profile, keyed by its own ``identifier``.

    Raises:
        UnknownProviderRuntimeError: ``selected`` is empty, ``None``, or does
            not match any key in ``profiles``.
    """
    if not selected:
        raise UnknownProviderRuntimeError("no provider identifier is configured")
    try:
        return profiles[selected]
    except KeyError:
        raise UnknownProviderRuntimeError(
            f"unknown provider identifier: {selected!r}"
        ) from None
