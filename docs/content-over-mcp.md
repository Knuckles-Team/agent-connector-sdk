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

`ConnectorContent` also carries the publishing package version. A composition
root that hosts declarative content from more than one package registers each
provider explicitly, then calls
`provision_connector_content(provider, sink=...)` once per provider. The SDK
captures each provider through its own in-process MCP listing and imports it
under that provider's connector identity; resources from two providers can
therefore never collapse into one ConnectorPack head or receipt.

## Content packs

`build_content_pack(session, connector=..., kinds=...)` reads every entry of the
given kinds from one session, validates each, and returns a captured generated
ConnectorPack archive. EG computes the canonical pack digest from that archive
and the current catalog snapshot, so the SDK never carries a second digest
implementation. Two entries with one URI, an unknown resource scheme, or a
malformed body are rejected.

Ontology and shapes bodies enter the generated archive as the exact served
UTF-8/LF bytes with `text/turtle`; connector packages must therefore publish
canonical LF files. The SDK does not parse or reserialize identity-bearing
Turtle. The generated archive builder supplies the section hashes, URI
ordering, and `mcp-server://<connector>` server entry. EG alone binds those
entries to the admitted catalog snapshot and canonical pack digest.

Pack facts are carried by EG's generated `PackAnnotations`: capability,
modality, cost, latency, and contract-version declarations come from the exact
`eg.annotations` key in MCP `_meta` (or skill front matter). Tools additionally
carry all explicitly served MCP safety hints and the SDK compatibility
fingerprint of their input/output contract. Conflicting declarations fail
closed instead of silently choosing one.

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
canonical input and output schemas. Generate pins from the live `tools/list`
response with [`connector-certify`](connector-certify.md). The package loader
fails closed on any other algorithm label.
