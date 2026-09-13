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
knowledge graph, token delegation, Eunomia policy middleware, OpenAPI tool
import, TLS client profiles (`core.transport_security`), and the env-var drift
checker.
