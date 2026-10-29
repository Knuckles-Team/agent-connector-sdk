# Implementation design: source client and virtual workspace

1. Add the typed source client module under `agent_connector_sdk/` with one
   frozen method per served `source.*` operation and the bounded digest-keyed
   blob cache.
2. Add the virtual workspace mount module over the client, sparse by declared
   prefix, with the pending changeset and its flush path.
3. Compose both behind the repository-manager connector's served development
   tools inside arbora MCP; compose the client directly in host-side tools
   that need source reads without a filesystem.
4. Prove the served path with the tests in `test-spec.md` against a
   controlled served backend; record the exact receipts in `spec.md`.

Each change is mergeable with its own focused tests. No step requires a live
deployment for ordinary pull-request validation.

## Existing system and reuse

- `create_http_client` at `agent_connector_sdk/http/client.py:92` and
  `create_async_http_client` at `agent_connector_sdk/http/client.py:117`
  supply the governed outbound transport and TLS policy. The client reuses
  them; no second transport is introduced.
- `agent_connector_sdk/credentials/` resolves `env://` and `openbao://`
  references. The client accepts credential references only; resolved values
  never enter logs, receipts, or cache entries.
- `register_tool_surface` at `agent_connector_sdk/mcp/tool_surface.py:305`
  is where the connector's served development tools register. `dispatch_async`
  at `agent_connector_sdk/mcp/action_dispatch.py:196` invokes their methods.
  The served side already exists in the SDK. This spec adds the client and
  the mount. The served side composes both. The SDK adds no new serving
  path.
- `SourceAdapter` at `agent_connector_sdk/ports/source_adapter.py:21` is the
  ingestion-side port. This spec does not reuse it. It extracts records from
  external sources into the graph service. The source client reads and
  commits development changesets.
- Reachable today: no. No source client, blob cache, or workspace mount
  exists in the SDK. Both are new modules with the reuse above.

## Architecture

Data flow: registered development tool (repository-manager connector) ->
`dispatch_async` -> served `source.*` operation -> SDK source client. The
reply comes from the served operation or the local cache. The caller
receives a typed page or receipt.

Write flow: development tool or mounted workspace -> pending changeset entry
-> flush -> `source.commit` through the client -> accepted receipt or stable
`conflict` code. Landing goes through `source.land`; revert through
`source.revert`. The client stores no authority and advances no revision
except by forwarding an accepted receipt.

The serving boundary is fixed. The served `source.*` operations live in the
serving side (arbora). The repository-manager connector exposes them as
connector tools inside arbora MCP. The SDK client is what the
connector or host composes. The SDK owns no serving, no tool registry, and
no admission or path-scope authorization. Admission and path-scope
authorization are enforced by the served operation before the client sees a
reply.

Failure modes: transport loss returns `transport_unavailable` with zero
effects. A mismatched cache digest evicts and re-reads. A conflicting write
returns `conflict` with the pending changeset intact. An oversized page
returns `oversized` and never truncates.

## Interfaces and data model

- A client request is a frozen value binding repository identity, revision or
  branch reference, optional path prefix, typed operation parameters, and the
  authenticated caller supplied by composition. Caller identity is never
  entered by the caller of a client method.
- A client result is a frozen typed page (entries or content bytes, page
  bounds, stable continuation) or a receipt (operation identity, revision,
  per-path outcomes). Continuations bind the request they continue; a
  continuation cannot migrate to another repository or revision.
- Cache entries are `digest -> (bytes, last_used)`. The bounds are named
  defaults for entry count and byte count; an admitted configuration may
  lower them. Verification is by digest on every read; a mismatch evicts.
- The pending changeset is an ordered map from path to one entry
  (operation, new blob reference or prior digest). It is scoped to one mount
  and one base revision; a changed base revision refuses the flush.

## Live integration path

Entry point: a registered development tool served by the repository-manager
connector inside arbora MCP. The tool builds the source client with the
authenticated caller and the served endpoint, then calls the matching typed
method. The mount consumes the same client for directory and blob reads and
records writes in its pending changeset. The effect boundary is the served
operation's accepted receipt; the SDK records no revision of its own.
Obsolete paths to delete: none. This spec adds modules; it retires nothing.

Cross-repository rows (pending filing in the owning repositories; linked by
ID, no SDK reimplementation is permitted):

- The served `source.*` operations, their admission, and the virtual
  checkout endpoint: arbora (operation rows filed under the arbora spec for
  served operations).
- Changeset storage, lock-free acceptance, derived history indexes, and path
  access control: epistemic-graph (filed under the epistemic-graph spec for
  source changesets).
- The in-run development loop that edits through changesets and reacts to
  `conflict`: agent-utilities.
- Git import/export and mirror sync for the public publishing surface:
  repository-manager connector.

## Quality and release gates

Focused: `uv run --frozen python -m pytest -q tests/test_source_client* tests/test_source_mount*`.
Type check: strict mypy over `agent_connector_sdk`.
Lint: Ruff check and format over changed files.
Spec gates: `pipelines-hook spec-standard`, `spec-decomposition`, `spec-status`, and `spec-trailers`.
Release: the repository's standard wheel build and gate suite; no new dependency is introduced by this spec.

## Risks, alternatives, and decisions

- Decision: one client module and one mount module, composed by the
  connector or host. Rejected alternative: a second SDK-side server that
  re-implements the served operations. It creates a duplicate serving
  authority and an admission bypass.
- Decision: the cache is a bounded digest-keyed local store, never an
  authority. Rejected alternative: a content-addressed local store that can
  serve reads without contacting the served operation. It splits blob
  authority between the cache and the serving side.
- Decision: FUSE is the default mount backend, with an overlay copy-up
  backend for hosts without FUSE. Rejected alternative: FUSE only. It leaves
  hosts without a FUSE kernel interface without a workspace.

## Amendments

### 2026-10-19: serving boundary refinement (SCION-SCM-R001, SCION-SCM-R002)

The development surface is served through the repository-manager connector's
tools, the development surface inside arbora MCP. The SDK client is what the
connector or host composes. The SDK owns no serving. This refinement bounds
both rows. No row may add a server, a served tool, an admission check, or a
registry entry. Any such need belongs to the serving-side or connector row,
not to this spec.

### Current served-contract inventory

At arbora `743c7d1e3607d76e373dedac33c4276567dfe68e`,
`arbora/api/ops/source.py` defines tree, blob, history and blame reads.
Their operation result wrappers currently expose `value: dict[str, Any]`,
and their outcomes do not expose page continuations. The source-write tasks
remain open. SCION-SCM-R001 requires frozen typed pages and receipts, stable
continuations and eight operations. The client needs an owner-backed contract
for these fields. SDK-only wire records cannot establish interoperability.
The repository-manager development tools and served proof remain prerequisites.

The current arbora source reader passes the `FileVersion.content_digest`
to `BlobFetchBegin` and returns that same string as `content_digest`. At
medulla `dc0c490a32753ef3e589ffb788a05caf42f20dea`, the fetch handler uses
that argument to look up a CAS manifest. The SDK cannot assume that it is
the SHA-256 of returned file bytes. Arbora
[`2de248dbb6b105242ed9d0ceb470d78e9c8425a7`](https://github.com/Knuckles-Team/arbora/commit/2de248dbb6b105242ed9d0ceb470d78e9c8425a7)
adds a separate hash of returned bytes. It does not establish an immutable
revision-bound authorization receipt. The current source reader
also performs separate engine reads rather than a demonstrated single snapshot.
A cache must not treat a mutable ref plus a byte hash as access authority.
The hash also does not prove a multi-read result is revision-consistent.
