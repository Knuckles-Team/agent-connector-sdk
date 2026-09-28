# SDK connector control, certification, and pack publication

**Program IDs:** EH-079, EH-135, EH-198, EH-199, EH-213, EH-214, EH-215, EH-217, EH-480–EH-486, EH-491, SDK hosted generated-contract repair lane, SDK hardened network serving lane.
**Owner:** agent-connector-sdk. **Delivery state:** UNKNOWN. **Acceptance state:** OPEN.
**Boundary:** This SDK owns source-side connector hosting, discovery, certification, pack construction, and submission. A graph service owns durable pack records and receipts; a control-plane service owns routing and activation policy. Vendor packages own their API calls.

## Outcome and scope

A fresh connector package can use one SDK server factory, one manifest, one credential-reference and HTTP/TLS stack, one certification command, and one generated graph client. Its published pack and tool pins are reproducible from the connector artifact, and the runner refuses uncertified or mismatched packages. Every migrated connector builds without importing `agent_utilities`. This is an SDK contract, not a requirement to copy any private fleet inventory.

The migration is five independently reviewable alphabetical batches: A–E (EH-480), F–J (EH-481), K–O (EH-482), P–S (EH-483), and T–Z (EH-484). Packages in a batch are selected from public connector repositories at implementation time, not from a hard-coded count. Those packages own their migration commits. EH-485 removes an old duplicate toolkit in the control-plane repository after consumers have migrated; EH-486 establishes the SDK as source lifecycle and certification owner while retiring the duplicate there. Connector base settings move into `agent_connector_sdk/config.py`; deployment settings and agent/model settings stay with their owners (EH-491).

## Architecture and contracts

```text
vendor connector package ──manifest and entry point──▶ SDK discovery/certify
        │                                          │ exact package tuple, tool schemas
        └──FastMCP tools/resources/prompts─────────┤
                                                   ▼
                          SDK artifact capture → canonical ConnectorPack
                                                   │ generated client + idempotency
                                                   ▼
                                  durable pack authority and receipt
```

1. A connector manifest names its package identity, server identity, tool pins, capabilities, credential references, source streams, and artifact annotations. Validate closed kinds, sorted unique entries, URI schemes, tenant scope, and no literal secrets before opening a session. Reuse `manifest/model.py`, `loader.py`, `live_contract.py`, `tool_schema.py`, `artifacts/pack.py`, and `certify/`; extend them instead of adding a parallel schema or publisher.
2. Certification binds **entry-point group + name + distribution + version**, runtime MCP server identity, tool name, normalized input schema digest, normalized output schema digest, and declared capability. A missing output schema is still fingerprinted canonically, never treated as an empty wildcard. Normalize schemas through `manifest/tool_schema.py`; SDK conformance tests own the pin calculation. The graph service stores a `contract_pin` as a claim attribute and must not be asked to recompute SDK normalization.
3. Pack publication uses the graph service's generated `ConnectorPack` and `AgentComponent.Content` request/response types. SDK forms a deterministic idempotency key over tenant, connector identity, canonical pack digest, and operation; a retry of an identical request returns the same durable result. Pack entry bodies remain content-addressed and bounded. No hand-written duplicate wire DTO and no placeholder content pack are allowed.
4. SQL-backed source record submission uses the generated `SourceIngest` request, checkpoint and receipt types through the existing SDK sink. The adapter declares table/key identity, change operation, schema digest, source version and provenance; the runner submits bounded pages only after live contract validation. The accepted receipt, not local success, advances the cursor. Reject null or mismatched tenant, schema, primary key and checkpoint fields before the graph call.
5. Pack annotations are a closed, canonical map per entry: capability names, input and output schema digests, modality, bounded cost and latency estimates with units, and provenance. Missing estimates mean `unknown`, never zero. The SDK validates types and units, excludes presentation-only fields from contract fingerprints, and includes semantic annotation changes in the pack digest. Re-certifying the fleet means each package produces current nonempty fingerprints for every declared pin and passes a current live-contract comparison; a package count alone is insufficient.
6. `mcp/server.py`, `mcp/action_dispatch.py`, `auth/`, `http/`, `tls/`, `credentials/`, and `ports/` remain the sole shared connector toolkit. `env://` and `openbao://` references may appear in manifests; resolved values may appear only in request memory, never logs, exceptions, packs, or reports. Unknown auth, public network exposure, or uncertified package tuple fails closed.
7. Connector-internal tool choice or inbound event triage may request a proposal from a decision service. This proposal is observational only. It never directly authorizes a side effect or bypasses deterministic write-back rules.
8. The release contract locks a published compatible graph-client wheel and verifies its generated types, native kernels, and error catalog in an isolated installed consumer. A source overlay, unpinned wheel, or stale lock cannot stand in for the release dependency.

## Portable development and contribution

Clone this public repository, install `uv` and Python matching `pyproject.toml`, run `uv sync`, then run the tests in `test-spec.md`. Unit tests use in-memory fake MCP sessions and fake generated-client ports; no tenant, hosted graph, secret store, or private connector fleet is needed. A contributor can add one synthetic fixture connector in `tests/fixture_package` and prove manifest, pin, pack, and failure behavior. Live publication is a later acceptance gate with a contributor-owned environment.

## Completion rule

Source is **LANDED** only after an exact merged commit contains the required implementation and checks. This spec is **ACCEPTED** only after the gates in `test-spec.md` pass against that commit and a published wheel plus a real connector pack receipt are linked in the evidence section below. Current implementation exists in `manifest/`, `certify/`, `mcp/`, `artifacts/`, and `runner/`, but fleet cutover and release acceptance are unverified here.

### Evidence

| Gate | Evidence | State |
|---|---|---|
| Exact merged SDK implementation | Pending exact commit | OPEN |
| Five batch consumer conformance | Pending batch receipts | OPEN |
| Published-wheel isolated consumer | Pending artifact digest and CI run | OPEN |
| Live pack publication and idempotent retry | Pending redacted receipt | OPEN |
