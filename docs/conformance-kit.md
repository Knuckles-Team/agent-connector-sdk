# Conformance kit

Every source adapter and artifact kind passes the same checks before it may be
activated. The kit lives in `agent_connector_sdk.testing`.

## Source adapters

`run_source_adapter_suite(adapter, sessions, malformed_sessions)` runs:

| Check | Passes when |
|---|---|
| capability descriptor | the descriptor names the adapter kind, the seam schema version and a pagination mode |
| pagination | more than one page is drained, the sweep ends exhausted, and no record id repeats |
| checkpoint resume | one page in one session plus the rest resumed in another equals an uninterrupted sweep |
| idempotent re-run | two sweeps yield identical record digests and cursors |
| malformed input rejection | a session serving malformed data makes extraction raise `MalformedSourceDataError` |
| provenance completeness | every record has complete provenance whose source URI names the record |

`sessions` and `malformed_sessions` are factories that open a fresh session per
call. The fixture behind `sessions` must serve at least two pages.

The SDK's own suite runs the kit against the `mcp_tool` adapter in every
pagination mode the fleet uses: cursor (the FreshRSS-style reader), page (the
ArchiveBox snapshot preset) and offset (a ServiceNow-style table tool).

## Artifact kinds

| Function | Checks |
|---|---|
| `check_artifact_kind(kind, sessions)` | the listing is not empty, every entry validates and maps to a record that references it, and two listings produce identical digests |
| `check_artifact_rejects_malformed(kind, entry)` | `validate` rejects a malformed entry |

## Write-back ports

`run_writeback_suite(factory)` requires a fresh scenario for each check and
proves that dry-run is side-effect free, stale base versions fail before the
transport mutates, an unverified authorization cannot write, a repeated
idempotency key cannot repeat an effect, and an uncertain outcome blocks retry
until reconciliation proves either the original effect or no effect. The
`make_writeback_fixture` reference uses only memory and never calls a vendor.

## Asserting

`assert_conformant(results)` raises `ConformanceFailure` naming every failed
check.
