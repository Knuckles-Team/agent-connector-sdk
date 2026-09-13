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
| `--health-addr` | unset | `PORT` or `HOST:PORT` serving `/health` and `/health/ready` (env `RUNNER_HEALTH_ADDR`); disabled unless set, and never started for `--once` |
| `--health-allow-non-loopback` | off | required to bind `--health-addr` to a non-loopback host |

Exit `2` means the runner could not start: an invalid configuration, an
uncertified extension, a malformed credential setting, or a malformed or
disallowed `--health-addr`.

!!! warning "Not done until W1"
    The `epistemic_graph` sink is the declared W1 stub. Until epistemic-graph
    publishes pack import and record ingestion, every cycle against it fails and
    logs `EG ... lands in RF-ADR-009 W1`. Its `readiness()` (see
    [Extension ports](extension-ports.md#sink)) always reports not ready, and
    that reason appears in `/health/ready`'s body: the sink cannot commit, so
    the runner cannot be ready.

## Health

`--health-addr` starts a small dependency-free HTTP listener (hand-rolled over
`http.server`, no framework) reporting the supervisor's own state -- not a
separate timer, so it can only ever say what the scheduler loop itself proved:

| Route | Meaning | 200 when | 503 body |
|---|---|---|---|
| `/health` | liveness: is the scheduler loop still ticking? | the loop completed a full reconcile pass within the liveness window (derived from `registry_refresh_seconds`, floor 30s) | `{"status": "error", "component": "scheduler_loop", "age_seconds": ..., "max_age_seconds": ...}` |
| `/health/ready` | readiness: can the runner do useful work right now? | the registry has loaded, every currently-registered connector's endpoint credentials resolved, and `sink.readiness()` reports ready | `{"status": "not_ready", "reasons": [...], "connectors": {...}}` |

`/health/ready` asks the configured `Sink` directly (its `readiness()` method
-- [Extension ports](extension-ports.md#sink)), bounded by a short timeout so
a sink whose readiness check hangs (a stalled network call, say) reports not
ready instead of hanging the probe request; the timeout itself becomes a
`"sink readiness timed out after ...s"` reason.

The heartbeat backing `/health` is updated by `ConnectorSyncRunner.run_forever`
itself immediately after `_reconcile()` returns -- there is no separate
timer thread, so a wedged registry read, a stuck worker start, or any other
hang inside that loop stops the heartbeat and `/health` goes `503` naming
`scheduler_loop`, exactly the signal a `pgrep`-based liveness probe cannot give.

`/health/ready`'s body always includes a `connectors` map, one entry per
connector the registry has ever listed, with no secret values:

```json
{
  "status": "not_ready",
  "reasons": ["credentials unresolved: freshrss-agent"],
  "connectors": {
    "freshrss-agent": {
      "last_success_seconds_ago": null,
      "consecutive_failures": 0,
      "next_retry_seconds": null,
      "credentials_ok": false,
      "credential_error": "connector 'freshrss-agent' has a credential reference that could not be resolved"
    }
  }
}
```

The listener binds loopback (`127.0.0.1`) by default -- `--health-addr 8765`
binds `127.0.0.1:8765` -- and refuses a non-loopback `--health-addr` (for
example `0.0.0.0:8765`, the bind a Kubernetes `httpGet` probe needs, since it
reaches the pod IP rather than the container's loopback interface) unless
`--health-allow-non-loopback` is also given.

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
