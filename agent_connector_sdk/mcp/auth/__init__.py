"""Authentication providers for connector MCP servers.

Extracted from the auth configuration in ``agent_utilities.mcp.server_factory``:
static tokens, JWT (including multi-realm), OAuth proxy, OIDC proxy and remote
OAuth. :func:`agent_connector_sdk.mcp.auth.factory.configure_auth` is the entry
point. Differences from AU:

* secrets arrive through :mod:`agent_connector_sdk.credentials` references;
* a JWKS URI discovered from an issuer uses an injectable HTTP client instead
  of AU's governed transport layer;
* token delegation and Eunomia policy middleware are not part of the SDK;
* invalid configuration raises ``AuthConfigurationError`` (the server factory
  exits) instead of exiting from deep inside the configuration code.
"""
