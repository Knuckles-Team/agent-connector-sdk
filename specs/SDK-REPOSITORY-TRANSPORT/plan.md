# Implementation design: repository transport

1. Preserve `repository/models.py`, `provider.py`, `transport.py`, `indexing.py` as the sole public transport path. Add provider adapters behind `RepositorySnapshotProvider`, not a second indexer.
2. Resolve a branch to immutable revision/tree once, authenticate, and bind every page and graph submission to that tuple. Fetch deterministic pages and validate paths/digests.
3. Diff against the last admitted revision, emit tombstones and changed files, maintain retryable failed/unsupported parse outcomes, and consume graph receipts before reporting completion.
4. Batch unique tree walks/object reads while preserving sorted output. Add reproducible benchmark and parity fixtures.
5. Cut consumers over to the SDK transport and graph-owned parsing; remove duplicate producer/consumer indexers after exact parity proof.
