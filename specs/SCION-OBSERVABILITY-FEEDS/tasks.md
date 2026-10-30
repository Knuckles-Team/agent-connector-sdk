# Tasks: operational feeds

- [ ] Implement common event envelope validation and durable replay path.
- [ ] Add RUM, security-audit and CI/CD adapter fixtures and provider implementations.
- [ ] Prove drift, duplicate, retention, privacy and backpressure behavior.
- [x] Record exact merged commits, CI tests and graph-backed restart receipt before acceptance (SCION-OBSERVABILITY-FEEDS-R001).

- [ ] Register the three event-feed adapter entry points (SCION-OBSERVABILITY-FEEDS-R001.5).
- [x] Bind the last event page to a bounded checkpoint digest and test exact replay and same-time distinct events (SCION-OBSERVABILITY-FEEDS-R001.6).
- [x] Prove one exact page across a worker process restart with an isolated graph (SCION-OBSERVABILITY-FEEDS-R001.3).
- [x] Bound the event identity index and refuse overflow before acceptance (SCION-OBSERVABILITY-FEEDS-R001.8).
- [x] Check an explicitly bound tenant before event identity deduplication (SCION-OBSERVABILITY-FEEDS-R001.7).
- [x] Activate declared event feeds through the connector-sync runner (SCION-OBSERVABILITY-FEEDS-R001.4).
