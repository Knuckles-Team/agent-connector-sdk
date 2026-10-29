# Tasks: repository transport

- [x] Complete immutable provider adapters and identity validation (SCION-REPOSITORY-TRANSPORT-R001, SCION-REPOSITORY-TRANSPORT-R002).
- [ ] Add changed-file/tombstone and failed-parse retry parity (SCION-SOURCE-INGEST-R005).
- [x] Batch unique tree walks and object reads, then publish reproducible before/after benchmark (SCION-REPOSITORY-TRANSPORT-R003).
- [ ] Attach exact merged commit, CI run, benchmark data, and graph receipt before acceptance.
- [x] Verify bounded, outcome-complete batch submission and that `IndexRepository` call count scales with batch count, not file count (SCION-REPOSITORY-TRANSPORT-R004, SCION-REPOSITORY-TRANSPORT-R005).
- [ ] Reject provider pages that exceed the requested size (SCION-REPOSITORY-TRANSPORT-R006).
- [ ] Bind local Git tree and blob reads to the selected commit (SCION-REPOSITORY-TRANSPORT-R007).
