# Extension ports

Four typed protocols keep the SDK open. An implementation ships in its own
distribution and declares an entry point; nothing in the SDK changes.

| Port | Module | Entry-point group | Reference implementation |
|---|---|---|---|
| `SourceAdapter` | `ports.source_adapter` | `agent_connector_sdk.source_adapters` | `mcp_tool` |
| `ArtifactKind` | `ports.artifact_kind` | `agent_connector_sdk.artifact_kinds` | `tools`, `skills`, `prompts`, `resources` |
| `Transport` | `ports.transport` | `agent_connector_sdk.transports` | `mcp` |
| `Sink` | `ports.sink` | `agent_connector_sdk.sinks` | `epistemic_graph` (declared seam, W1) |

## SourceAdapter

| Method | Contract |
|---|---|
| `describe()` | capabilities, without I/O |
| `discover(session)` | verify the live source contract; required before extraction |
| `extract(session, cursor)` | one page and the cursor that resumes after it |
| `reconcile(session, known_ids)` | ids missing from the source and unknown to the sink |

The `mcp_tool` adapter extracts through a connector's MCP tool as a preset
describes it (cursor or page pagination, a since-watermark), requires the pinned
`tool_schema_sha256`, and rejects records that do not match the preset. The
watermark advances only when a sweep is exhausted.

## Activation

`load_extension(group, name, policy=...)` loads an extension only when the
activation policy certifies its exact group, name, distribution and version.
There is no permissive default. `sdk_reference_extensions()` certifies the
implementations this SDK version ships. Two distributions declaring the same
name in a group is an error.

## Seam types

`agent_connector_sdk.contracts` holds the record, cursor, pack and receipt types
the SDK exchanges with epistemic-graph. epistemic-graph owns that schema; when it
publishes the contract, these types are replaced by generated ones.
