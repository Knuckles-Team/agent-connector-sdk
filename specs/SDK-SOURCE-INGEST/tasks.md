# Tasks: source sync

- [x] Finish generated-client checkpoint and receipt path; remove parallel cursor assumptions (SDK-SOURCE-INGEST-R001, SDK-SOURCE-INGEST-R004).
- [x] Implement pure normalized drift classifier, quarantine report, and declared evolution policy (SDK-SOURCE-INGEST-R002, SDK-SOURCE-INGEST-R007).
- [x] Implement proposal-only repair handoff and graph-owned activation proof (SDK-SOURCE-INGEST-R003).
- [x] Port enterprise, document/session/feed, and enrichment adapters through SDK ports (SDK-SOURCE-INGEST-R004–SDK-SOURCE-INGEST-R006).
  - [x] Web-fetch requests-floor backend ported to `agent_connector_sdk.adapters.web_fetch` (HTTP GET via the SDK's own governed client, OG/Twitter Card metadata, tag-strip text normalization) (SDK-SOURCE-INGEST-R005).
  - [x] Web-fetch: ArchiveBox and crawl4ai backends (still call agent-utilities-owned MCP fleet / crawler subprocess infrastructure) (SDK-SOURCE-INGEST-R005).
  - [x] Web-fetch: richer HTML-to-markdown conversion (markitdown or equivalent) in place of the tag-strip floor (SDK-SOURCE-INGEST-R005).
  - [x] Web-fetch: wrapped as `WebFetchSourceAdapter` (`ports.SourceAdapter`), registered via the `agent_connector_sdk.source_adapters` entry-point group; one URL per extracted page, checkpoint-recoverable, reconcile against a fixed URL set (SDK-SOURCE-INGEST-R005).
  - [x] Package-install ingestion and repository-related transport adapters (SDK-SOURCE-INGEST-R005).
- [ ] Record exact merged commit, CI run, fixture results, and graph-backed restart receipt before acceptance.
- [x] Add occurrence/weather adapters (GBIF, iNaturalist, NOAA GHCN/ISD, Open-Meteo, NOAA storm events) and the NCBI/GBIF taxonomy connector validated against `TaxonShape` (SDK-SOURCE-INGEST-R008, SDK-SOURCE-INGEST-R009).
- [ ] Add the ingest worker runner and the `ingest-worker` command; the engine decides admission, lane floors and routing (SDK-SOURCE-INGEST-R010, SDK-SOURCE-INGEST-R011).
- [ ] **R005.1:** Implement and verify paper-source model acceptance (SDK-SOURCE-INGEST-R005.1).
- [ ] **R005.2:** Implement and verify paper-source behavior acceptance (SDK-SOURCE-INGEST-R005.2).
- [ ] **R005.3:** Implement and verify paper-source wiring acceptance (SDK-SOURCE-INGEST-R005.3).
- [ ] **R005.4:** Implement and verify paper-source refusal acceptance (SDK-SOURCE-INGEST-R005.4).
- [ ] **R005.5:** Implement and verify paper-source evidence acceptance (SDK-SOURCE-INGEST-R005.5).
- [ ] **R005.6:** Implement and verify paper-source hot-path proof acceptance (SDK-SOURCE-INGEST-R005.6).

- [ ] **SDK-SOURCE-INGEST-R012:** Platform read/search fallback and observed backend status.
- [ ] **SDK-SOURCE-INGEST-R012.1:** Model.
- [ ] **SDK-SOURCE-INGEST-R012.2:** Behavior.
- [ ] **SDK-SOURCE-INGEST-R012.3:** Wiring.
- [ ] **SDK-SOURCE-INGEST-R012.4:** Refusal.
- [ ] **SDK-SOURCE-INGEST-R012.5:** Evidence.
- [ ] **SDK-SOURCE-INGEST-R012.6:** Hot-path proof.

## Concurrent stage resume

- [ ] `SDK-SOURCE-INGEST-R001.1`: implement and prove model for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.2`: implement and prove behavior for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.3`: implement and prove wiring for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.4`: implement and prove refusal for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.5`: implement and prove evidence for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.6`: implement and prove hot-path proof for concurrent stage resume.

## Native SQL source execution

- [ ] `SDK-SOURCE-INGEST-R004.1`: implement and prove model for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.2`: implement and prove behavior for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.3`: implement and prove wiring for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.4`: implement and prove refusal for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.5`: implement and prove evidence for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.6`: implement and prove hot-path proof for native sql source execution.

## Offline bookmark import

- [ ] `SDK-SOURCE-INGEST-R005.7`: implement and prove model for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.8`: implement and prove behavior for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.9`: implement and prove wiring for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.10`: implement and prove refusal for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.11`: implement and prove evidence for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.12`: implement and prove hot-path proof for offline bookmark import.

## Chain transaction-log decoding

- [ ] `SDK-SOURCE-INGEST-R005.13`: implement and prove model for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.14`: implement and prove behavior for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.15`: implement and prove wiring for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.16`: implement and prove refusal for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.17`: implement and prove evidence for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.18`: implement and prove hot-path proof for chain transaction-log decoding.

## Parallel workspace document reads

- [ ] `SDK-SOURCE-INGEST-R005.19`: implement and prove model for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.20`: implement and prove behavior for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.21`: implement and prove wiring for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.22`: implement and prove refusal for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.23`: implement and prove evidence for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.24`: implement and prove hot-path proof for parallel workspace document reads.

## Interchangeable enterprise operations

- [ ] `SDK-SOURCE-INGEST-R006.32`: implement and prove model for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.33`: implement and prove behavior for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.34`: implement and prove wiring for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.35`: implement and prove refusal for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.36`: implement and prove evidence for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.37`: implement and prove hot-path proof for interchangeable enterprise operations.
