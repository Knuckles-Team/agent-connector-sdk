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
describes it (pagination, a since-watermark), requires the pinned
`tool_schema_sha256`, and rejects records that do not match the preset. The
watermark advances only when a sweep is exhausted.

| `pagination` | Parameters | Next page |
|---|---|---|
| `none` | | none |
| `cursor` | `cursor_param`; `cursor_path` or `cursor_record_field`; optional `more_path` | the token, until it is absent or repeats |
| `page` | `page_param`, `page_size_param`, `page_size`, `start_page`; `page_kind` `number` or `page` | the next page index, until a page is shorter than `page_size` |
| `offset` | `page_param` (the offset), `page_size_param`, `page_size`; `page_kind` `offset` | the offset plus the records returned, until a page is shorter than `page_size` |

A `page_kind` that does not apply to the mode is rejected. A preset with an
empty `id_field` is rejected: a sweep without record identity, such as a SQL
table sweep, belongs to a data-platform source adapter (RF-ADR-009 section 2.3).

The package validator also rejects a `tool_schema_sha256` equal to the
fingerprint of an empty input schema. Such a pin verifies nothing and matches no
live server; re-certify it from the server's `tools/list`.

## Sink

| Method | Contract |
|---|---|
| `submit(batch)` | commit a record batch; the receipt is returned only after commit |
| `import_pack(pack)` | import a content pack keyed by its digest |
| `readiness()` | whether this sink can commit right now, without side effects -- returns a `SinkReadiness(ready, reason)`; `reason` is set whenever `ready` is `False` and must never carry a credential or other secret value |

The connector-sync runner's `/health/ready` (see [Connector sync](connector-sync.md)
"Health") calls `readiness()` directly, bounded by a short timeout, so a sink
implementation must answer it without a side effect and should not assume it
is ever skipped. `epistemic_graph` (the declared W1 seam) always reports not
ready, naming the wave that lands it; the testing kit's `InMemorySink` always
reports ready.

## Runner ports

The connector-sync runner adds three ports, described in
[Connector sync](connector-sync.md): `ConnectorRegistry` (`ports.connector_registry`),
`CheckpointStore` (`ports.checkpoint_store`) and `ChangeSource`
(`ports.change_source`).

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
