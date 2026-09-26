# Status

This page summarizes the current repository and package surface. The implementation,
generated Epistemic Graph contracts, and repository quality gates remain the
authoritative detail.

| Area | Availability | Current contract |
|---|:---:|---|
| Python package | Available | Version 0.1.0; Python 3.12–3.14 |
| Connector MCP server | Available | `create_mcp_server` with the shared security, health, content, and tool-surface policies |
| Connector certification | Available | `connector-certify` checks live MCP schemas and pinned fingerprints without invoking vendor actions |
| Source synchronization | Available | `connector-sync` supervises certified adapters and advances only from matching Epistemic Graph receipts |
| Epistemic Graph sink | Available through verified composition | Requires an injected generated client and live ConnectorPack authority resolver |
| Repository ingestion | Available | Immutable snapshot paging into the generated `IndexRepository` operation with bounded transfer and typed outcomes |
| Governed write-back | Available | Generated change sets and authorization decisions drive preview, apply, and reconciliation |
| Extension conformance | Available | Reusable suites cover source adapters, artifact kinds, transports, sinks, and write-back ports |

## Runtime authority

Graph-bound operation is composed by Graph OS. It injects verified identity,
the generated Epistemic Graph client, and current catalog authority. The SDK
fails closed when a required dependency, source receipt, authorization decision,
or extension certification is absent or does not match.

## How status is checked

- `/health` reports the scheduler loop's observed liveness.
- `/health/ready` reports connector credentials, registry state, and sink
  readiness from the live dependencies.
- [Capabilities](capabilities.md) maps each supported surface to its public
  guide.
- [Quality gates](quality-gates.md) lists the checks applied to every release.
