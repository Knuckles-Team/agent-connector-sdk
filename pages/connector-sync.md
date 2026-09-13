# Connector sync

`connector-sync` is one supervised scheduler for every connector (RF-ADR-009
sections 2.1 and 2.2). For each connector it opens one MCP session through the
`Transport` port and uses it for everything:

1. **Provisioning.** It reads the server's tools, skills, prompts and resources
   as a content pack. When the pack digest equals the digest the sink last
   acknowledged, nothing happens. Otherwise the pack is imported, and the digest
   is recorded only from the sink's receipt.
2. **Sync.** It runs the manifest `sync` presets through the `mcp_tool` source
   adapter. Every page goes to the sink as a batch. The cursor is recorded only
   after the sink's receipt acknowledges that exact batch and cursor, and the
   next page is requested from that committed cursor. After a crash, the stream
   resumes from the last committed page.
3. **Changes.** It subscribes with `subscriptions/listen` to the list changes and
   to updates of the pack's resources and the descriptor's data resources.
   A list change, or an update to a pack resource, re-provisions. An update to a
   mapped data resource syncs its presets. Without listen support, the
   notifications the server sends on its own still count, and the connector's
   `interval_seconds` schedule runs a full cycle.

## Running

```bash
connector-sync --config runner.yml                # serve until stopped
connector-sync --config runner.yml --once         # one cycle per connector
```

| Option | Default | Meaning |
|---|---|---|
| `--config` | required | runner configuration (YAML or JSON) |
| `--state-dir` | `$XDG_STATE_HOME/connector-sync` | checkpoint directory |
| `--sink` | `epistemic_graph` | sink extension name |
| `--once` | off | exit `0` only when every connector succeeded, otherwise `1` |
| `--log-format` | `json` | `json` (one object per line) or `text`, on stderr |

Exit `2` means the runner could not start: an invalid configuration, an
uncertified extension or a malformed credential setting.

!!! warning "Not done until W1"
    The `epistemic_graph` sink is the declared W1 stub. Until epistemic-graph
    publishes pack import and record ingestion, every cycle against it fails and
    logs `EG ... lands in RF-ADR-009 W1`.

## Configuration

```yaml
settings:
  max_concurrency: 4            # cycles running at once, runner-wide
  backoff_initial_seconds: 5    # per connector, doubling after each failure
  backoff_max_seconds: 600
  registry_refresh_seconds: 60  # how often the registry is re-read
connectors:
  - connector: freshrss-agent
    package_root: ../agents/freshrss-agent            # holds connector_manifest.yml
    connectors_dir: ../agents/freshrss-agent/freshrss_agent/connectors
    endpoint:
      url: https://freshrss-mcp.example.invalid/mcp
      bearer_token: openbao://apps/freshrss-agent#MCP_TOKEN
    interval_seconds: 900
    data_resources:
      data://freshrss-agent/reading-list: [freshrss]
```

| Connector field | Meaning |
|---|---|
| `endpoint.url` or `endpoint.command` + `args` | streamable HTTP or stdio |
| `endpoint.bearer_token`, `endpoint.env` | credential references only (`env://`, `openbao://`); a literal value is rejected |
| `endpoint.client_credentials` | instead of `bearer_token`: `issuer` or `token_url`, `client_id`, `client_secret_ref`, `audience`, `scope`; the token is cached per connector, refreshed before expiry and re-minted once on a 401 (see [HTTP clients](http-clients.md#mcp-endpoints)) |
| `presets` | presets to run; empty means every `sync` preset of the manifest |
| `provision` | whether the content pack is provisioned |
| `data_resources` | resource URI to the presets synced when it is updated |
| `mapping_reference` | the mapping the sink applies; default `manifest:<connector>` |
| `max_pages_per_cycle` | pages one cycle reads per preset; the next cycle resumes |

Relative paths are resolved against the configuration file. The package is
validated before any session opens (manifest, presets and pinned fingerprints
must agree), and credential references are resolved before the session opens.
Any failure fails that connector closed and retries it with backoff.

## Ports

| Port | Purpose | Implementations |
|---|---|---|
| `ConnectorRegistry` | the connectors to serve, re-read periodically | `StaticConfigRegistry`; epistemic-graph's server registry after W1 |
| `CheckpointStore` | committed cursors and imported pack digests, written only from receipts | `JsonFileCheckpointStore`; an EG-backed store after W1 |
| `ChangeSource` | change events of a session | the MCP transport's sessions |
| `Transport`, `Sink`, `ArtifactKind`, `SourceAdapter` | see [Extension ports](extension-ports.md) | |

## Log events

| `event` | Fields |
|---|---|
| `connector_started`, `connector_stopped` | `connector` |
| `pack_imported`, `pack_unchanged` | `pack_digest`, `imported` |
| `stream_synced` | `stream`, `pages`, `records`, `accepted`, `exhausted` |
| `change_subscription` | `listening`, `resources` |
| `connector_failed` | `error`, and `retry_in` when serving |
| `registry_unreadable` | `error` |
