"""Outbound credentials for a connector's vendor API, always by reference.

Inbound authentication of the connector's own MCP server lives in
:mod:`agent_connector_sdk.mcp.auth`; this package authenticates the connector to
the systems it calls. Every constructor that needs a secret takes an ``env://``
or ``openbao://`` reference, never a value.

* :mod:`~agent_connector_sdk.auth.static`: bearer, HTTP Basic and API-key auth.
* :mod:`~agent_connector_sdk.auth.client_credentials`: the OAuth 2.0
  client-credentials grant with token caching and refresh.
* :mod:`~agent_connector_sdk.auth.delegation`: RFC 8693 token exchange on behalf
  of the MCP caller.
* :mod:`~agent_connector_sdk.auth.tokens`: token endpoint requests.

Replaces ``agent_utilities.mcp.client_credentials``,
``agent_utilities.mcp.delegated_auth`` and ``mcp_auth_config``.
"""
