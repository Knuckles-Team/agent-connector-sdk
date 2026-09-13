# agent-connector-sdk

The SDK every connector in the agent-packages fleet builds on. It holds three
things that used to live inside agent-utilities:

| Area | What it gives a connector |
|---|---|
| MCP server scaffolding | `create_mcp_server`, authentication, visibility filtering, the condensed and verbose tool surface, action dispatch |
| Declarative content | the connector manifest schema and validator, sync presets, pinned tool-schema fingerprints, and serving skills, prompts, ontologies, shapes and the manifest as MCP primitives |
| Extension ports | typed `SourceAdapter`, `ArtifactKind`, `Transport` and `Sink` protocols discovered through entry points, with a conformance kit |

## Where it sits

The workspace builds in a fixed order, and a repository may only depend on
earlier phases. The SDK is phase 3.

| Phase | Repository | Relation to the SDK |
|---|---|---|
| 2 | epistemic-graph | the SDK uses its Python client; epistemic-graph owns the pack and record schema |
| 3 | agent-connector-sdk | this repository |
| 4 | agent-utilities | the agent plane; not a dependency of the SDK |
| 7 | connectors (`agents/*`) | depend on the SDK and the epistemic-graph client only |

## Status

This is the first release of the SDK (0.1.0). The epistemic-graph sink is a
declared contract seam: epistemic-graph publishes its pack-import and ingestion
methods in RF-ADR-009 wave W1, and until then the sink raises
`NotImplementedError`. Everything else on these pages is implemented and tested.
