"""Connect a connector process to epistemic-graph for knowledge ingest.

Opt-in by configuration only: nothing connects unless ``EPISTEMIC_GRAPH_ENDPOINT``
is set. Settings:

================================== =============================================
``EPISTEMIC_GRAPH_ENDPOINT``       ``tls://host:port``, ``tcp://host:port``
                                   (loopback only) or ``unix:///path``
``EPISTEMIC_GRAPH_AUTH_SECRET_REF`` secret reference to the engine auth secret
``EPISTEMIC_GRAPH_TENANT``         tenant the connector ingests into
``EPISTEMIC_GRAPH_GRAPH``          target graph
``EPISTEMIC_GRAPH_PRINCIPAL``      service principal (default ``service:connector``)
``EPISTEMIC_GRAPH_POLICY_VERSION`` policy version claim (default ``policy:current``)
================================== =============================================

TLS material comes from the ``epistemic-graph`` TLS profile
(:func:`agent_connector_sdk.tls.resolve.resolve_tls_profile`). The client runs
on one daemon event-loop thread owned by this module.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from epistemic_graph.client import EpistemicGraphClient

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import CredentialResolver
from agent_connector_sdk.ingest.errors import IngestUnavailableError
from agent_connector_sdk.ingest.service import KnowledgeIngest
from agent_connector_sdk.ingest.transport import EpistemicGraphIngestTransport
from agent_connector_sdk.mcp.exposure import is_loopback_host
from agent_connector_sdk.tls.resolve import resolve_tls_profile

__all__ = ["INGEST_SCOPES", "EngineSettings", "connect_ingest"]

#: The only engine scopes a connector's ingest session asks for.
INGEST_SCOPES = ("source:ingest", "blob:write")
_CONNECT_TIMEOUT_S = 30.0
_REQUIRED = ("auth_secret_ref", "tenant", "graph")


@dataclass(frozen=True)
class EngineSettings:
    """How this process reaches epistemic-graph; credentials only by reference."""

    endpoint: str
    auth_secret_ref: str
    tenant: str
    graph: str
    principal: str = "service:connector"
    policy_version: str = "policy:current"

    def __post_init__(self) -> None:
        missing = [name for name in _REQUIRED if not getattr(self, name)]
        if missing:
            raise IngestUnavailableError(
                "EPISTEMIC_GRAPH_ENDPOINT is set but "
                + ", ".join(f"EPISTEMIC_GRAPH_{name.upper()}" for name in missing)
                + " is not"
            )

    @classmethod
    def from_settings(cls) -> EngineSettings | None:
        """The configured settings, or ``None`` when no endpoint is configured."""
        endpoint = str(setting("EPISTEMIC_GRAPH_ENDPOINT", "")).strip()
        if not endpoint:
            return None
        return cls(
            endpoint=endpoint,
            auth_secret_ref=str(setting("EPISTEMIC_GRAPH_AUTH_SECRET_REF", "")),
            tenant=str(setting("EPISTEMIC_GRAPH_TENANT", "")),
            graph=str(setting("EPISTEMIC_GRAPH_GRAPH", "")),
            principal=str(setting("EPISTEMIC_GRAPH_PRINCIPAL", "service:connector")),
            policy_version=str(
                setting("EPISTEMIC_GRAPH_POLICY_VERSION", "policy:current")
            ),
        )

    def verified_context(self) -> dict[str, Any]:
        """The request-context claims this service signs its requests with."""
        return {
            "principal": self.principal,
            "tenant": self.tenant,
            "audience": "epistemic-graph",
            "agent_id": self.principal,
            "roles": ["connector"],
            "scopes": list(INGEST_SCOPES),
            "policy_version": self.policy_version,
            "delegation": [],
        }

    def address(self) -> dict[str, Any]:
        """``connect`` keyword arguments naming the endpoint and its transport security.

        Raises:
            IngestUnavailableError: the scheme is unknown or plaintext TCP names a
                non-loopback host.
        """
        parts = urlsplit(self.endpoint)
        if parts.scheme == "unix" and parts.path:
            return {"socket_path": parts.path}
        if parts.scheme not in {"tls", "tcp"} or not parts.hostname or not parts.port:
            raise IngestUnavailableError(
                "EPISTEMIC_GRAPH_ENDPOINT is not a valid endpoint"
            )
        if parts.scheme == "tcp" and not is_loopback_host(parts.hostname):
            raise IngestUnavailableError(
                "plaintext epistemic-graph TCP is loopback-only"
            )
        address: dict[str, Any] = {"tcp_addr": f"{parts.hostname}:{parts.port}"}
        if parts.scheme == "tls":
            address["tls"] = resolve_tls_profile("epistemic-graph").ssl_context
            address["tls_server_hostname"] = parts.hostname
        return address


def _engine_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=loop.run_forever, name="agent-connector-sdk-ingest", daemon=True
    )
    thread.start()
    return loop


def connect_ingest(
    settings: EngineSettings,
    *,
    resolver: CredentialResolver | None = None,
    timeout_s: float = _CONNECT_TIMEOUT_S,
) -> KnowledgeIngest:
    """Connect to epistemic-graph and return an ingest service bound to its loop.

    Raises:
        IngestUnavailableError: the endpoint, secret or connection is unavailable.
    """
    try:
        secret = resolve_secret_reference(settings.auth_secret_ref, resolver)
        kwargs = settings.address()
    except IngestUnavailableError:
        raise
    except Exception as exc:
        raise IngestUnavailableError("epistemic-graph ingest is misconfigured") from exc
    loop = _engine_loop()
    connecting = EpistemicGraphClient.connect(
        auth_secret=secret,
        graph_name=settings.graph,
        verified_context=settings.verified_context(),
        **kwargs,
    )
    try:
        client = asyncio.run_coroutine_threadsafe(connecting, loop).result(timeout_s)
    except Exception as exc:
        loop.call_soon_threadsafe(loop.stop)
        raise IngestUnavailableError("epistemic-graph is unreachable") from exc
    return KnowledgeIngest(EpistemicGraphIngestTransport(client), loop=loop)
