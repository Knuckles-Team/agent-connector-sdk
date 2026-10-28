# Tasks: operational feeds

- [ ] Implement common event envelope validation and durable replay path.
- [ ] Add RUM, security-audit and CI/CD adapter fixtures and provider implementations.
- [ ] Prove drift, duplicate, retention, privacy and backpressure behavior.
- [x] Record exact merged commits, CI tests and graph-backed restart receipt before acceptance (SDK-OBSERVABILITY-FEEDS-R001).

- [ ] Register the three event-feed adapter entry points (SDK-OBSERVABILITY-FEEDS-R001.5).
- [x] Bind the last event page to a bounded checkpoint digest and test exact replay and same-time distinct events (SDK-OBSERVABILITY-FEEDS-R001.6).
- [x] Bound the event identity index and refuse overflow before acceptance (SDK-OBSERVABILITY-FEEDS-R001.8).
- [x] Check an explicitly bound tenant before event identity deduplication (SDK-OBSERVABILITY-FEEDS-R001.7).
