# Moving from agent-utilities

Connectors that imported agent-utilities move to these modules. The imports
counted are the fleet's measured imports before the move.

| agent-utilities import | Imports | SDK module | Change |
|---|---:|---|---|
| `core.config.setting`, `load_config` | 209 | `config` | `load_config` reads the SDK's own config file and rejects credential values |
| `mcp.concurrency` | 207 | `mcp.concurrency` | same functions |
| `mcp.action_dispatch` | 196 | `mcp.action_dispatch` | same functions |
| `core.exceptions` | 105 | `exceptions` | same classes |
| `core.decorators.require_auth` | 44 | `exceptions.require_auth` | moved |
| `base_utilities` | 101 | `utilities` | `get_logger`, `to_boolean`, `to_integer`, `to_float`; values are not environment-expanded |
| `mcp.server_factory.create_mcp_server` | 71 | `mcp.server` | everything after `name` is keyword-only and `version` is required |
| `mcp.verbose_tools.register_tool_surface` | 70 | `mcp.tool_surface` | `autowire_condensed` and `force_condensed_registration` removed (unused in the fleet) |
| `mcp.context_helpers.ctx_log` | 7 | `mcp.context.ctx_log` | `ctx_log(ctx, message, *, logger, level)` |
| `security.brain_context` actor types | 62 | `identity` | `ActorContext`, `ActorType`, `use_actor`, `current_actor` |
| `knowledge_graph.memory.native_ingest` | 64 | `ports.sink.Sink` | records go to a sink; the epistemic-graph sink lands with W1 |
| `knowledge_graph.core.session` | 60 | epistemic-graph client | no SDK equivalent; connectors call epistemic-graph directly |
| `knowledge_graph.ontology.connector_manifest` | — | `manifest.model` | generator heuristics stay with the manifest generator |
| `protocols.source_connectors` registry | — | `discovery` | entry points and an explicit activation policy |
| `mcp_tool` source connector | — | `adapters.mcp_tool` | emits raw records; documents, ACLs, detail fetches and SQL sweeps are not extraction |
| `core.transport_security.ResolvedTLSProfile` | 129 | `tls.profile.ResolvedTLSProfile` | adds `minimum_version`; `redis_kwargs` and `child_env` removed (no connector used them) |
| `core.transport_security.resolve_configured_tls_profile` | 96 | `tls.resolve.resolve_tls_profile` | settings are read directly; no `AgentConfig` projection |
| `core.transport_security.resolve_tls_profile` | 46 | `tls.resolve.resolve_tls_profile` | `environ` removed; `destination_root` is `runtime_root`; `ca_ref`/`ca_pem`/`ca_path` aliases removed |
| `core.transport_security.TransportSecurityError` | 1 | `tls.errors.TransportSecurityError` | same codes |
| `mcp.delegated_auth.is_delegation_enabled` | 20 | `auth.delegation.DelegationSettings.from_settings().enabled` | `OIDC_TOKEN_URL` and `OIDC_CLIENT_SECRET_REF` replace discovery and a secret value |
| `mcp.delegated_auth.get_delegated_token` | 18 | `auth.delegation.DelegatedTokenAuth`, `exchange_token` | per-request auth with a per-caller cache |
| `mcp.delegated_auth.get_user_identity` | 5 | `auth.delegation.current_user_identity` | returns the opaque reference string |
| `mcp.delegated_auth.get_user_token` | 1 | `auth.delegation.current_user_token` | only a token the server's auth verified |
| `mcp.server_factory.mcp_auth_config` | 2 | `auth.delegation.DelegationSettings` | a typed, validated value instead of a mutable dict |
| `core.http_client.create_http_client` | 4 | `http.client.create_http_client` | takes `HttpClientOptions`; retries, logging and problem errors built in |
| `core.http_client.create_async_http_client` | 2 | `http.client.create_async_http_client` | as above |
| `mcp.client_credentials.ClientCredentialsTokenProvider` | 1 | `auth.client_credentials.ClientCredentialsTokenProvider` | `client_secret_ref` and a governed `http_client` |
| `mcp.context_helpers.ctx_progress` | 6 | `progress.ctx_progress` | adds `message`; validates values; delivery failure is logged |

## Entry points

| agent-utilities group | SDK |
|---|---|
| `agent_utilities.skill_providers` | serve `skills/` with `ConnectorContent` |
| `agent_utilities.prompt_providers` | serve `prompts/` with `ConnectorContent` |
| `agent_utilities.ontology_providers` | serve `ontology/` with `ConnectorContent` |
| `agent_utilities.source_connector_providers` | the manifest `sync` section and `agent_connector_sdk.source_adapters` |

## Not in the SDK

These server features stay with agent-utilities or graph-os: the WorkItem tasks
extension, engine-backed `/metrics`, semantic tool filtering through the
knowledge graph, Eunomia policy middleware, OpenAPI tool import, and the env-var
drift checker.

These connector imports have no SDK replacement; the connectors drop them:

| agent-utilities import | Imports | Why not |
|---|---:|---|
| `core.http_client.pinned_egress_transport` | 1 | DNS pinning against a caller-chosen host depends on agent-utilities' egress policy; a connector reaches a configured base URL |
| `mcp.client_credentials.child_auth_header` | 1 | the multiplexer's ambient `MCP_CLIENT_AUTH` identity; use `auth.oidc.client_credentials_auth` |
| `core.workspace.initialize_workspace`, `get_agent_workspace`, `get_mcp_config_path` | 5 | the agent plane's workspace (`agent_server.py`, repository-manager scripts), not API clients |
| `core.paths.log_dir`, `skills_dir` | 3 | agent-utilities' XDG layout; skills are served over MCP |
