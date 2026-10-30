# Changelog

## 0.6.3

### Fixed

- The MCP rate limiter runs after the actor binding and keys on the bound actor, so
  stdio and every HTTP mode share one middleware stack and one identity decision. The
  trusted local principal (`SYSTEM_ACTOR`: stdio, in-process, `--auth-type none`) is not
  throttled; other principals keep 10 requests/s, burst 20, each in their own bucket
  (SCION-CONNECTOR-CONTROL-R025.6).
- New `scion_sdk.privacy.sanitize_tool_response` redacts only secrets from tool results
  and errors and keeps local paths visible; connectors use it instead of
  `sanitize_for_persistence` for responses (SCION-CONNECTOR-CONTROL-R025.7).

## 0.6.2

### Fixed

- `--auth-type none` (or `AUTH_TYPE=none`) over streamable HTTP starts and serves, on
  loopback or any address; a non-loopback listener logs one warning. Every request is
  `SYSTEM_ACTOR`, the same principal as stdio. An unset auth type still refuses HTTP
  (SCION-CONNECTOR-CONTROL-R025.3).
- One token-to-actor resolution (`actor_binding.token_actor`) serves both the request
  binding and the served security profile. A token without a tenant claim is in its
  issuer's tenant, so an IdP client-credentials token is no longer refused with an
  opaque `access denied`; refusals now read `access denied: <reason>`
  (SCION-CONNECTOR-CONTROL-R025.2, R014.18).
- `CONNECTOR_PRINCIPAL_GRANTS` entitles a token principal by config
  (SCION-CONNECTOR-CONTROL-R025).

## 0.6.1

### Fixed

- A server started with `--auth-type none` binds `SYSTEM_ACTOR` to every HTTP request,
  the same as stdio, so a no-auth deployment behind a gateway reaches its resources
  again. `ANONYMOUS_ACTOR` stays for a tokenless request to a server with auth
  configured. The auth mode comes from the network serving config
  (SCION-CONNECTOR-CONTROL-R025.3).
- Entitlement refusals name their cause: `anonymous_caller`, `authentication_required`,
  `tenant_required` or `not entitled to <namespace>:<resource>`. New
  `scion_sdk.entitlements.require_entitled` raises `EntitlementError` with that reason
  (SCION-CONNECTOR-CONTROL-R025).

## 0.6.0

### Changed

- **Breaking (0.6.0):** the import package moves from `agent_connector_sdk`
  to `scion_sdk`. Each entry-point group now starts with `scion_sdk.`. The pytest plugin
  is `scion_sdk.testing.plugin`. The pyproject table is `[tool.scion_sdk]`. The bundled
  skill is `scion-sdk-development`. Config lives in `$XDG_CONFIG_HOME/scion-sdk`.
  No alias module exists. Wire identifiers keep their values: the access ontology IRI,
  the tool-contract fingerprint domains and the problem-type URN prefix.

- `current_actor()` needs no prior `use_actor(...)` call. With no bound actor, it
  resolves the caller from the request transport. A request without HTTP gets
  `SYSTEM_ACTOR`. An authenticated HTTP request gets its token actor. An unauthenticated
  HTTP request gets `ANONYMOUS_ACTOR`. Remove any `use_actor(SYSTEM_ACTOR)` bootstrap.
  `use_actor` stays as an explicit override (SCION-CONNECTOR-CONTROL-R025.5).

- The OAuth file store now uses complete-key digests. Its old filenames
  collided, so existing file-store users must sign in again.

- Manual OAuth completion now requires the complete redirect URL. A raw code
  has no state binding and is refused.

### Removed

- The `agent-connector-sdk` forwarder distribution (`compat/`) and its build and publish
  jobs are gone. Depend on `scion-sdk>=0.6.0,<0.7.0` directly.
- `scion_sdk.paths` no longer reads `GRAPH_OS_CONFIG_DIR`, `AGENT_UTILITIES_CONFIG_DIR`, `~/.config/graph-os` or `~/.config/agent-utilities`; the platform config lives under `ARBORA_CONFIG_DIR` / `~/.config/arbora` only. `legacy_platform_config_dir(s)` are removed.

## 0.5.5

### Added

- Declared sources carry edges (SDK-SOURCE-INGEST-R004.36). `EdgeSpec` and
  `IngestSourceSpec.edges` declare, in `source_meta(edges=...)`, the
  relationship from each record to the record a reference field names (owner,
  steward, assignment group, assignee). `SourceSyncRunner` emits the referenced
  target records and the relationships with the record batch. The pack
  ontology must declare each relationship as an object property whose domain
  is the source record type.

## 0.5.4

### Fixed

- `scion_sdk.artifacts.pack` no longer maps `manifest://` resources
  to `PackEntryKind.MANIFEST`, which `epistemic-graph` 2.27.6 removed. The SDK
  imported with `AttributeError` on a fresh install. A `manifest://` resource
  now has no pack entry kind and `build_content_pack` refuses it
  (SDK-CONNECTOR-CONTROL-R075.7).

### Changed

- The `epistemic-graph` floor is now `>=2.27.6`. The lock, the release pin and
  the pinned import-graph fixtures resolve `epistemic-graph` 2.27.6.

## 0.5.3

### Added

- `Connector` declares typed bootstrap hooks (SDK-CONNECTOR-CONTROL-R019.2):
  `tool_registry`, `action_tools` with `action_prefixes`, `inline_tools`,
  `routes` (`Route`), `readiness` (`Readiness` at `GET /ready`) and
  `content_root`. `build_server` applies each through the fastmcp API.
- `RegistrationContext` in `scion_sdk.connector_hooks`. It carries
  the server, the fleet name, the version and the parsed settings. It also
  carries the client factory and the authentication provider.
- `register_action_tools(mcp, entries, prefixes=...)` and a `prefix` argument
  on `split_action_tool`.
- `scion_sdk.config_mounts` holds the schema and the validation of
  `[[tool.pipelines.container.config_mounts]]` (SDK-CONNECTOR-CONTROL-R019.3).
  The `config_mounts` conformance check runs it.
- `ConnectorContentDirs.content`, the directory that holds the content kinds.

### Changed

- `Connector.extra_registrations` callables receive a `RegistrationContext`
  instead of the bare server, and `ingest_registration` returns such a
  callable. The pipelines central connector codemod migrates connector
  repositories, so no connector needs a hand edit.
