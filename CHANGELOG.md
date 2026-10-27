# Changelog

## Unreleased

### Removed

- `agent_connector_sdk.paths` no longer reads `GRAPH_OS_CONFIG_DIR`, `AGENT_UTILITIES_CONFIG_DIR`, `~/.config/graph-os` or `~/.config/agent-utilities`; the platform config lives under `ARBORA_CONFIG_DIR` / `~/.config/arbora` only. `legacy_platform_config_dir(s)` are removed.

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

- `agent_connector_sdk.artifacts.pack` no longer maps `manifest://` resources
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
- `RegistrationContext` in `agent_connector_sdk.connector_hooks`. It carries
  the server, the fleet name, the version and the parsed settings. It also
  carries the client factory and the authentication provider.
- `register_action_tools(mcp, entries, prefixes=...)` and a `prefix` argument
  on `split_action_tool`.
- `agent_connector_sdk.config_mounts` holds the schema and the validation of
  `[[tool.pipelines.container.config_mounts]]` (SDK-CONNECTOR-CONTROL-R019.3).
  The `config_mounts` conformance check runs it.
- `ConnectorContentDirs.content`, the directory that holds the content kinds.

### Changed

- `Connector.extra_registrations` callables receive a `RegistrationContext`
  instead of the bare server, and `ingest_registration` returns such a
  callable. The pipelines central connector codemod migrates connector
  repositories, so no connector needs a hand edit.
