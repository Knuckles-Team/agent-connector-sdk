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
