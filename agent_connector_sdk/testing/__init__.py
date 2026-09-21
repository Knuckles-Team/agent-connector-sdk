"""Conformance kit for source adapters and artifact kinds (RF-ADR-009 2.2.1).

Every adapter and artifact kind must pass the same checks before it may be
activated, the way epistemic-graph modality runtimes must pass the modality
TCK before they may be served.

* :mod:`~agent_connector_sdk.testing.source_adapters`: capability descriptor,
  pagination, checkpoint resume, idempotent re-run, malformed input rejection
  and provenance completeness.
* :mod:`~agent_connector_sdk.testing.artifact_kinds`: listing, validation,
  deterministic digests, record mapping and malformed entry rejection.
* :mod:`~agent_connector_sdk.testing.results`: result types and
  :func:`~agent_connector_sdk.testing.results.assert_conformant`.
* :mod:`~agent_connector_sdk.testing.writeback`: dry-run, optimistic conflict,
  authorization, idempotency and uncertain-outcome reconciliation checks.

Fixtures must exercise the checks: a source serving at least two pages, and a
session factory that opens a fresh session per call.
"""
