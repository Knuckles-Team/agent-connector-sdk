# Implementation design: operational feeds

1. Add a shared event-envelope validation layer using existing `SourceAdapter`, manifest, runner and generated-client sink contracts.
2. Implement RUM, security-audit and CI/CD provider adapters independently; keep vendor-specific parsing in their connector repositories.
3. Bind checkpoint/replay to durable receipts and add schema drift quarantine before submission.
4. Run offline fixtures, then opt-in contributor-owned feed and graph integration with redacted receipts.
