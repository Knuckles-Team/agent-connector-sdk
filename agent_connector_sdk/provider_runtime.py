"""Provider-runtime profile resolution for multi-backend connectors.

A connector that supports more than one backend implementation (for example
audiobookshelf-mcp, pulselink-mcp, fan-manager, or vector-mcp selecting among
several vector-store providers) registers one :class:`ProviderRuntimeProfile`
per supported provider identifier and resolves the configured selection with
:func:`resolve_selected_provider_runtime_profile`. Resolution rejects an
unconfigured or unknown provider identifier before any request is attempted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_connector_sdk.config import ConfigurationError

__all__ = [
    "ProviderRuntimeProfile",
    "resolve_selected_provider_runtime_profile",
]


@dataclass(frozen=True)
class ProviderRuntimeProfile:
    """Runtime shape of one backend provider for a multi-backend connector.

    Attributes:
        provider_id: The identifier a connector's configuration selects this
            profile by (for example ``"openai"`` or ``"qdrant"``).
        base_url: The provider's API base URL.
        auth_mode: How the client authenticates against this provider (for
            example ``"bearer"``, ``"api_key"``, or ``"none"``).
        capabilities: Capability flags the client that constructs requests
            uses to decide which request shapes the provider supports.
    """

    provider_id: str
    base_url: str
    auth_mode: str
    capabilities: Mapping[str, bool] = field(default_factory=dict)


def resolve_selected_provider_runtime_profile(
    selected_provider: str | None,
    profiles: Mapping[str, ProviderRuntimeProfile],
) -> ProviderRuntimeProfile:
    """Return the runtime profile for ``selected_provider`` in ``profiles``.

    Args:
        selected_provider: The provider identifier read from the connector's
            configuration. ``None`` or empty means no provider was configured.
        profiles: The connector's registered profile set, keyed by provider
            identifier.

    Returns:
        The matching :class:`ProviderRuntimeProfile`.

    Raises:
        ConfigurationError: ``selected_provider`` is unset, or is not a key
            in ``profiles``. Raised before any network call is attempted.
    """
    if not selected_provider:
        raise ConfigurationError(
            "no provider configured: set the connector's provider identifier "
            "before any request is attempted"
        )
    try:
        return profiles[selected_provider]
    except KeyError as exc:
        known = ", ".join(sorted(profiles)) or "<none registered>"
        raise ConfigurationError(
            f"unknown provider '{selected_provider}': registered providers are {known}"
        ) from exc
