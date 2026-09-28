# Implementation design: connector control

1. Freeze the public manifest and generated graph-client boundary; list every existing SDK extension point and remove duplicate representations instead of creating aliases.
2. Complete canonical input/output schema fingerprints, package tuple certification, annotation validation, and deterministic pack idempotency in current `manifest/`, `certify/`, and `artifacts/` modules.
3. Keep server factory, auth, HTTP, TLS, credentials, visibility, and action dispatch behind SDK APIs. Migrate connector packages in the five named batches with one synthetic public fixture first; re-target package templates to those APIs.
4. Replace legacy source and connector toolkit imports at consumer boundaries. Remove old toolkit only after import scans and independent package tests pass. Preserve vendor behavior in each connector, not the SDK.
5. Lock the published graph-client wheel, build the SDK wheel, run offline unit/conformance checks, then run an opt-in environment-backed pack publication and retry probe. Record commit, wheel digest, and redacted receipt in `spec.md`.

Each slice is mergeable with its own conformance tests. No step requires a live home deployment for ordinary pull-request validation.
