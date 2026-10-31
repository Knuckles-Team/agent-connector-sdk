# Connector servers

## Building a server

`scion_sdk.mcp.server.create_mcp_server(name, *, version, ...)` parses
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

## Declared connectors

A connector package declares a `Connector` value and calls
`scion_sdk.run()`; the SDK builds the server above from it. Anything
the server does beyond the plain bootstrap is a typed `Connector` field, applied
through fastmcp's own API:

| Field | Applied as |
|---|---|
| `tool_registry` | `(tag, toggle_setting, registrar)` entries, used instead of `tools` |
| `action_tools`, `action_prefixes` | registrars whose action-routed tools are served one typed tool per action, named `<prefix>_<action>` |
| `inline_tools` | functions or fastmcp `Tool` values, added with `FastMCP.add_tool` |
| `routes` | `Route(path, handler, methods, name)`, added with `FastMCP.custom_route`; never `/health` or `/ready` |
| `readiness` | an async probe returning `Readiness(ready, detail)`, served at `GET /ready` (200 or 503) |
| `extra_registrations` | callables that receive a `RegistrationContext(server, name, version, settings, client_factory, auth)` |
| `content_root` | a package-relative directory holding `skills/`, `prompts/`, `ontology/` and `connectors/` |

A container that reads a reference-only configuration directory declares it in
`pyproject.toml`. The shared container renderer adds a read-only bind mount. The
conformance plugin checks the table against `CONFIG_MOUNTS_SCHEMA` from
`scion_sdk.config_mounts`:

```toml
[[tool.pipelines.container.config_mounts]]
source = "${CONNECTOR_CONFIG_DIR:?set-CONNECTOR_CONFIG_DIR}"
target = "/etc/connector"
```

## Change subscriptions

Every server built by `create_mcp_server` serves `subscriptions/listen`, so
clients such as the connector-sync runner learn about changes without polling.
`scion_sdk.mcp.change_events` publishes them:

| Function | Publishes |
|---|---|
| `announce_content_changed(mcp)` | the tool, prompt and resource lists changed |
| `announce_resource_updated(mcp, uri)` | the resource at `uri` was updated |
| `serve_change_subscriptions(mcp, bus=None)` | serves listen streams on a server not built by the factory; returns the bus |
| `change_bus(mcp)` | the server's bus, for a shared cross-replica implementation |

A connector that publishes `announce_resource_updated` for a data resource lets
the runner sync that resource's presets as soon as it changes.

## Network exposure

A `streamable-http` or `sse` listener outside loopback is refused unless it has
all three of: an authentication mode other than `none`, a TLS boundary (a
certificate and key, or `--tls-terminated` with `--trusted-proxy-cidrs`), and an
exact `--allowed-hosts` list.

Build the serving boundary once and pass it intact to FastMCP:

```python
from scion_sdk.mcp.network import build_network_serving_config

serving = build_network_serving_config(args)
if serving is None:
    mcp.run(transport="stdio")
else:
    mcp.run(
        transport=args.transport,
        host=args.host,
        port=args.port,
        **serving.fastmcp_run_kwargs(),
    )
```

The typed configuration enforces exact Host and browser/WebSocket Origin
allowlists, a bounded request body with a read timeout, and the immediate-peer
CIDR for TLS-stop ingress. Its Uvicorn policy disables forwarded-header
trust and bounds concurrency, listen backlog, keepalive, graceful shutdown, and
the incomplete HTTP-event buffer. Direct TLS certificate and key paths are
validated before the listener starts.

| Bound | Default | Setting / flag |
|---|---:|---|
| request body | 4 MiB | `MCP_MAX_REQUEST_BYTES` / `--max-request-bytes` |
| body read timeout | 30 s | `MCP_REQUEST_BODY_TIMEOUT_SECONDS` / `--request-body-timeout-seconds` |
| concurrent connections | 128 | `MCP_MAX_CONNECTIONS` / `--max-connections` |
| listen backlog | 256 | `MCP_LISTEN_BACKLOG` / `--listen-backlog` |
| keepalive timeout | 5 s | `MCP_KEEPALIVE_TIMEOUT_SECONDS` / `--keepalive-timeout-seconds` |
| graceful shutdown | 15 s | `MCP_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` / `--graceful-shutdown-timeout-seconds` |

Invalid values refuse startup; they never fall back to an unbounded listener.

## Authentication

| `--auth-type` | Needs |
|---|---|
| `static` | `--static-tokens-ref` naming a JSON token map |
| `jwt` | `--token-issuer`, `--token-audience`, and a JWKS URI, public key, or `--token-secret-ref` for HMAC; comma lists configure multiple realms |
| `oauth-proxy` | upstream endpoints, client id, `--oauth-upstream-client-secret-ref`, base URL and JWT settings |
| `oidc-proxy` | `--oidc-config-url`, client id, `--oidc-client-secret-ref`, base URL and token audience |
| `remote-oauth` | authorization servers, base URL and JWT settings |

An unknown mode is an error, never an unauthenticated server. With
`--public-base-url`, JWT servers publish RFC 9728 protected-resource metadata.

## Tool surface

`register_tool_surface(mcp, service=..., client_cls=Api, get_client=...)`
registers one MCP tool per API operation: one per public method of the client
class, named `<prefix>_<operation>`. A fleet gateway scales the catalog through
lazy `find` and load. The SDK tags every tool `gated`, and the gateway reveals it on demand.

| Tool property | Source |
|---|---|
| Name | `<prefix>_<method>`; `prefix` is `tool_prefix` or the service name without `-mcp`/`-agent`/`-api`/`-server` |
| Input schema | the OpenAPI operation manifest (`manifest=`), else the method signature and type hints |
| Description | the manifest summary, else the docstring |
| Annotations | the HTTP verb: GET is read-only; DELETE is destructive; PUT and DELETE are idempotent; other verbs are not read-only |

Registrars (`tools_module`, `tool_registry` or `registrars`) add the tools that
are not client-method wrappers, such as ingest tools; each honours a
`<TAG>TOOL` setting. With a client, the SDK splits a registrar tool that routes
an `action` string into one typed tool per action. An action that an operation
tool serves stays with that tool. `register_action_tools(mcp, entries, prefixes=...)`
splits action tools with or without a client. `action_dispatch=True` keeps them
whole for compatibility. No environment mode selects the surface. A destructive
operation asks the connected user to confirm and is cancelled when it cannot.

## Visibility

`MCP_ENABLED_TOOLS`, `MCP_DISABLED_TOOLS`, `MCP_ENABLED_TAGS` and
`MCP_DISABLED_TAGS` set the server policy. HTTP clients may narrow it with query
parameters or `x-mcp-*` headers, never widen it. A malformed filter exposes
nothing.

## Platform read and search fallback

A connector passes a `PlatformFallback` to `create_mcp_server`. It may register
the same tools through a `register_tool_surface` registrar. The host binds an
authenticated actor for each call. It supplies an authorizer, certified backend
admission, and named retry policies. Network hosts use `VerifiedScopeAuthorizer`
to match the token subject, tenant, and scope. Missing identity or denied
authorization refuses before an outbound call. The host validates continuations.
Each continuation stays pinned to its original backend.

`PlatformHttpBackend` uses pinned governed egress. It performs one HTTP attempt
per call. The fallback client owns the retry budget and total deadline. Status
is a short-lived observation scoped to the caller and capability. It is not a
grant. A refused platform result cannot advance source synchronization.

## Caller identity

A connector never binds an actor at startup. Call `scion_sdk.identity.current_actor()`
inside a tool and it resolves the caller per request. There is one resolution path for
every transport: the factory installs the same `ActorBindingMiddleware` on stdio and
HTTP, and the transport only supplies the credential.

| mode | how it is started | actor |
|---|---|---|
| stdio | `--transport stdio`, an in-process client, startup, background work | `SYSTEM_ACTOR` (every resource) |
| no-auth HTTP | `--transport streamable-http --auth-type none` (explicit) | `SYSTEM_ACTOR` (every resource) |
| authenticated HTTP | any other `--auth-type` | the token's subject, tenant, roles and groups |

`--auth-type none` must be chosen explicitly; with the auth type unset the factory
refuses to serve HTTP. On a non-loopback address a no-auth listener logs one warning
and serves: run it only behind a boundary such as arbora. With an auth provider, a
request without a token gets HTTP 401. A token that names no tenant claim is in its
issuer's tenant.

Grant a principal capabilities through config, not code: its IdP roles and groups, or
`CONNECTOR_PRINCIPAL_GRANTS`, for example `arbora=ssh:*;backup-bot=ssh:nas`. A
principal matches the token's `sub`, `client_id`, `azp` or `preferred_username`.

### Entitlements

`scion_sdk.entitlements` decides which resources an actor may reach. A role or group
`<namespace>:<resource>` grants one resource (`ssh:lab`), `<namespace>:*` grants the
namespace, and `admin` or `system` grants everything. `identity_scoped_resources`
lists the entitled subset. `require_entitled(namespace, resource)` refuses with an
`EntitlementError` that names the cause and never a secret:

| reason | meaning |
|---|---|
| `anonymous_caller` | no token reached a server with auth configured |
| `authentication_required` | the actor has no verified identity |
| `tenant_required` | the identity names no tenant |
| `not_entitled` | `not entitled to <namespace>:<resource>` |

The factory installs `ActorBindingMiddleware`. The middleware turns identity refusals,
entitlement refusals included, into typed JSON-RPC `-32000` errors whose message starts
with the reason. An authenticated caller without the entitlement is always denied.
Use `use_actor(...)` only as an explicit override in tests or embedding code.
A connector removes any `use_actor(SYSTEM_ACTOR)` bootstrap.
