"""Read current ConnectorPack authority from GraphOS over authenticated MCP.

The GraphOS tool derives authority from its verified request session. The SDK
supplies only the requested connector and checks the returned generated EG
contracts against the tenant and service principal of its verified EG client.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from epistemic_graph.generated.connector_pack import (
    AgentLibraryMutationContext,
    McpCatalogSnapshotBinding,
)
from pydantic import ValidationError

from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport

__all__ = ["CatalogAuthorityError", "RemotePackImportAuthorityResolver"]


class CatalogAuthorityError(RuntimeError):
    """GraphOS did not provide authority bound to this connector and caller."""


_OPAQUE_PRINCIPAL = re.compile(r"principal:sha256:[0-9a-f]{64}\Z")


def _opaque_principal(principal: str) -> str:
    """Match EG's canonical persistence principal for one verified actor ID."""
    if _OPAQUE_PRINCIPAL.fullmatch(principal):
        return principal
    return "principal:sha256:" + hashlib.sha256(principal.encode("utf-8")).hexdigest()


class RemotePackImportAuthorityResolver:
    """Resolve each import against live GraphOS authority, without a local cache.

    ``tenant`` and ``principal`` must come from the same verified identity as
    the EG sink client. A process may reuse this adapter while its OIDC client
    credentials refresh; GraphOS validates the fresh bearer on every request.
    """

    def __init__(
        self,
        endpoint: TransportEndpoint,
        *,
        tenant: str,
        principal: str,
        transport: McpTransport | None = None,
    ) -> None:
        url = urlsplit(endpoint.url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise CatalogAuthorityError("catalog authority requires a secure MCP URL")
        if not endpoint.url or endpoint.auth is None or endpoint.bearer_token:
            raise CatalogAuthorityError(
                "catalog authority requires an authenticated MCP URL"
            )
        if (
            not tenant
            or not principal
            or tenant != tenant.strip()
            or principal != principal.strip()
        ):
            raise CatalogAuthorityError(
                "catalog authority needs verified tenant and principal"
            )
        self._endpoint = endpoint
        self._tenant = tenant
        self._principal = _opaque_principal(principal)
        self._transport = transport or McpTransport()

    async def __call__(
        self, connector: str
    ) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
        if not isinstance(connector, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{0,127}", connector
        ):
            raise CatalogAuthorityError("connector identity is invalid")
        try:
            async with self._transport.session(self._endpoint) as session:
                response = await session.call_tool(
                    "connector_pack_authority", {"connector": connector}
                )
        except Exception as exc:
            raise CatalogAuthorityError(
                "GraphOS catalog authority request failed"
            ) from exc
        return self._validate_response(response, connector)

    def _validate_response(
        self, response: Any, connector: str
    ) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
        if not isinstance(response, Mapping) or set(response) != {
            "connector",
            "catalog_binding",
            "mutation_context",
        }:
            raise CatalogAuthorityError("GraphOS catalog authority response is invalid")
        if response["connector"] != connector:
            raise CatalogAuthorityError("GraphOS catalog authority connector differs")
        try:
            catalog = McpCatalogSnapshotBinding.model_validate(
                response["catalog_binding"]
            )
            context = AgentLibraryMutationContext.model_validate(
                response["mutation_context"]
            )
        except ValidationError as exc:
            raise CatalogAuthorityError(
                "GraphOS catalog authority contracts are invalid"
            ) from exc
        if (
            context.tenant_id != self._tenant
            or context.caller_principal != self._principal
        ):
            raise CatalogAuthorityError("GraphOS catalog authority caller differs")
        return catalog, context
