"""The declared connector and the one function that serves it.

A connector package declares its fleet name once, as the single entry point of
the ``scion_sdk.connector`` group, and names a :class:`Connector`
value::

    [project.entry-points."scion_sdk.connector"]
    searxng-mcp = "searxng_mcp:connector"

    # searxng_mcp/__init__.py
    from scion_sdk.connector import Connector
    from searxng_mcp.api_client import Api
    from searxng_mcp.auth import get_client

    connector = Connector(api=Api, get_client=get_client, instructions="...")

:func:`run` resolves that declaration and serves the connector: transport
flags, authentication, health, middleware, fleet registration and the package's
skills, prompts, ontology, shapes and ``connector://resources`` all come from
the SDK (SCION-CONNECTOR-CONTROL-R019.1). The package holds no server bootstrap,
no ``__version__`` and no ``__main__`` logic.

Content is found by convention under the package named by the entry point:
``skills/``, ``prompts/``, ``ontology/``, ``connectors/`` and
``connector_sources`` (SCION-CONNECTOR-CONTROL-R071.1). No provider entry points
are needed; ``content_root`` names a package-relative directory instead.

A server that did more than the plain bootstrap declares it on ``Connector``
with the typed hooks of :mod:`scion_sdk.connector_hooks`
(SCION-CONNECTOR-CONTROL-R019.2).
"""

from __future__ import annotations

from scion_sdk._connector_decl import (
    Connector,
    ConnectorContentDirs,
    ResolvedConnector,
    content_dirs,
    installed_connectors,
    resolve_connector,
)
from scion_sdk._connector_serve import build_server, run

__all__ = [
    "Connector",
    "ConnectorContentDirs",
    "ResolvedConnector",
    "build_server",
    "content_dirs",
    "installed_connectors",
    "resolve_connector",
    "run",
]
