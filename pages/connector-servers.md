# Connector servers

## Building a server

`agent_connector_sdk.mcp.server.create_mcp_server(name, *, version, ...)` parses
the standard command line, refuses unsafe exposure, configures authentication,
and returns `(args, mcp, middlewares)`. The caller adds the middlewares.

| Argument | Purpose |
|---|---|
| `version` | reported to clients; required |
| `content` | a `ConnectorContent` to serve as MCP primitives |
| `server_registry` | a `ServerRegistry` whose lease the server renews while it runs |
| `credential_resolver` | resolves secret references in authentication flags |

Every server gets a `GET /health` route, per-caller rate limiting, and error
handling that never returns tracebacks.

## Network exposure

A `streamable-http` or `sse` listener outside loopback is refused unless it has
all three of: an authentication mode other than `none`, a TLS boundary (a
certificate and key, or `--tls-terminated` with `--trusted-proxy-cidrs`), and an
exact `--allowed-hosts` list.

## Authentication

| `--auth-type` | Needs |
|---|---|
| `static` | `--static-tokens-ref` naming a JSON token map |
| `jwt` | `--token-issuer`, `--token-audience`, and a JWKS URI, public key, or `--token-secret-ref` for HMAC; comma lists configure several realms |
| `oauth-proxy` | upstream endpoints, client id, `--oauth-upstream-client-secret-ref`, base URL and JWT settings |
| `oidc-proxy` | `--oidc-config-url`, client id, `--oidc-client-secret-ref`, base URL and token audience |
| `remote-oauth` | authorization servers, base URL and JWT settings |

An unknown mode is an error, never an unauthenticated server. With
`--public-base-url`, JWT servers publish RFC 9728 protected-resource metadata.

## Tool surface

`register_tool_surface(mcp, service=..., ...)` registers condensed
action-routed tools and, in `verbose` or `both` mode, one tool per API method
plus `tool__action` aliases derived from the condensed tools.

| `MCP_TOOL_MODE` | Condensed tools | Verbose tools |
|---|---|---|
| `intent` (default) | registered and tagged `gated` | no |
| `condensed` | registered | no |
| `verbose` | registered; gated when a verbose surface exists | yes |
| `both` | registered | yes |

Each condensed registrar honours a `<TAG>TOOL` setting. A destructive operation
asks the connected user to confirm and is cancelled when it cannot.

## Visibility

`MCP_ENABLED_TOOLS`, `MCP_DISABLED_TOOLS`, `MCP_ENABLED_TAGS` and
`MCP_DISABLED_TAGS` set the server policy. HTTP clients may narrow it with query
parameters or `x-mcp-*` headers, never widen it. A malformed filter exposes
nothing.
