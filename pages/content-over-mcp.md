# Content over MCP

A connector declares its content once, in its package, and serves it through
the MCP primitives agents already use. Provisioning reads the same listings, so
what an agent can call is exactly what the knowledge graph records.

## What is served

`register_connector_content(mcp, ConnectorContent(...))` registers:

| Package path | MCP primitive | Artifact kind | Record kind |
|---|---|---|---|
| `skills/<name>/SKILL.md` | `skill://<name>/SKILL.md` resource | `skill` | `Skill` |
| `prompts/<name>.json` | prompt `<name>` | `prompt` | `McpPrompt` |
| `ontology/<file>.ttl` | `ontology://<connector>/<file>.ttl` | `resource` | `Ontology` |
| `ontology/shapes/<file>.ttl` | `shapes://<connector>/<file>.ttl` | `resource` | `ShapesGraph` |
| `connector_manifest.yml` | `manifest://connector` | `resource` | `ConnectorManifest` |
| the server's tools | `tools/list` | `tool` | `Tool` |

A prompt file that has no `instructions.core_directive`, or a declared manifest
that does not exist, is an error when the server starts.

## Content packs

`build_content_pack(session, connector=..., kinds=...)` reads every entry of the
given kinds from one session, validates each, and returns a `ContentPack`. Its
digest is a canonical hash over the server identity and the entry digests, so an
unchanged server produces an unchanged digest. Two entries with one URI, an
unknown resource scheme, or a malformed body are rejected.

## Manifest, presets and fingerprints

A connector package carries three declarations of its sync contract:

| File | Loader |
|---|---|
| `connector_manifest.yml` | `load_manifest` |
| `connectors/mcp_source_presets.json` | `load_tool_presets` |
| `connectors/tool_schema_fingerprints.json` | `load_tool_schema_fingerprints` |

`require_valid_connector_package(package_root)` fails when they disagree: a sync
entry that names a preset that does not exist, a mirrored field that differs, a
fingerprint that does not match, or a preset the manifest does not declare.
Fingerprints use the
`agent-connector-sdk:mcp-tool-contract-compat:v2` algorithm, which binds the
canonical input and output schemas. The old input-only pins must be replaced
from the live `tools/list` response with
[`connector-certify`](connector-certify.md); the package loader fails closed on
the old algorithm label.
