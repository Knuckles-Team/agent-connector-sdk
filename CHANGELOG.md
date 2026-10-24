# Changelog

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
