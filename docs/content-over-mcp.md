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
| tool `meta` from `source_meta` | `connector://resources` | `resource` | `ConnectorResources` |
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

`scion_sdk.artifacts.tool_facts.schema_tokens(body)` estimates the
token count of a canonical captured tool body. It rounds the UTF-8 byte count up
by four. This is an estimate, not a tokenizer measurement. It does not publish
the count in a pack annotation.

The factory's exact `connector://status` endpoint exposes operational state.
Resource capture excludes this endpoint from packaged content. The `connector://capability/{capability}`
template remains available for direct reads; capture does not list template
instances. Other unknown resources, including other `connector://` URIs, still fail
validation.

Ontology and shapes bodies enter the generated archive as the exact served
UTF-8/LF bytes with `text/turtle`; connector packages must therefore publish
canonical LF files. The SDK does not parse or reserialize identity-bearing
Turtle. The generated archive builder supplies the section hashes, URI
ordering, and `mcp-server://<connector>` server entry. EG alone binds those
entries to the admitted catalog snapshot and canonical pack digest.

Pack facts are carried by EG's generated `PackAnnotations`: capability,
modality, cost, latency, and contract-version declarations come from the exact
`eg.annotations` key in MCP `_meta` (or skill front matter). Tools also
carry all explicitly served MCP safety hints and the SDK compatibility
fingerprint of their input/output contract. Conflicting declarations fail
closed instead of silently choosing one.

## Declaration and fingerprints

A connector declares its data sources in code: `source_meta(...)` on each read
tool. The server serves the assembled declaration as the JSON resource
`connector://resources`: sources, record-type mappings onto the ontology,
resources and data-resource descriptors. The runner and `connector-certify`
read that resource and nothing else.

Fingerprints use the `agent-connector-sdk:mcp-tool-contract-compat:v2`
algorithm, which binds the canonical input and output schemas. The SDK reads
the fingerprint from the live `tools/list` response; no file pins it.
