# agent-connector-sdk

The shared runtime and development kit for connector packages. It gives each
connector a secure MCP server, declarative content, typed source and write-back
ports, governed HTTP behavior, and a common conformance contract.

| Area | Capability |
|---|---|
| MCP runtime | `create_mcp_server`, authentication, safe exposure, visibility, action dispatch, change subscriptions |
| Connector content | manifests, sync presets, fingerprints, skills, prompts, ontologies, and SHACL shapes |
| Source synchronization | certified adapters, transports, sinks, durable acknowledgements, cursor discipline, and health |
| Write-back | dry-run, authorization, optimistic version checks, idempotency, and uncertain-effect reconciliation |
| Connector development | governed HTTP and TLS, credential references, extension discovery, certification, and conformance suites |

## Ownership boundary

The SDK owns connector transport and lifecycle behavior. A connector owns its
vendor API requests, source revisions, paging tokens, and external effects.
`epistemic-graph` owns durable graph records, schemas, validation, reasoning,
receipts, and semantic indexing. Agent runtimes own goals, workflows, routing,
and model calls.

Connectors depend on this SDK and the epistemic-graph client. The SDK does not
depend on an agent framework.

## Runtime readiness

Extensions activate only when their exact package identity and capabilities are
certified. Sink readiness is queried directly and bounded by a timeout. A sink
that cannot commit reports not ready; `connector-sync` exposes that result at
`/health/ready` and does not advance a cursor.

The bundled epistemic-graph sink in version 0.1.0 is not commit-capable. Use the
readiness endpoint as the runtime authority; no pack or record batch is accepted
through that sink while it reports `ready=false`.

Start with [Connector servers](connector-servers.md), then configure
[Connector sync](connector-sync.md) and validate each extension with the
[Conformance kit](conformance-kit.md).
