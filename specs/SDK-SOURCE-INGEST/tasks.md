# Tasks: source sync

- [ ] Finish generated-client checkpoint and receipt path; remove parallel cursor assumptions (SDK-SOURCE-INGEST-R001, SDK-SOURCE-INGEST-R004).
- [ ] Implement pure normalized drift classifier, quarantine report, and declared evolution policy (SDK-SOURCE-INGEST-R002, SDK-SOURCE-INGEST-R007).
- [ ] Implement proposal-only repair handoff and graph-owned activation proof (SDK-SOURCE-INGEST-R003).
- [ ] Port enterprise, document/session/feed, and enrichment adapters through SDK ports (SDK-SOURCE-INGEST-R004–SDK-SOURCE-INGEST-R006).
- [ ] Record exact merged commit, CI run, fixture results, and graph-backed restart receipt before acceptance.
- [ ] Add occurrence/weather adapters (GBIF, iNaturalist, NOAA GHCN/ISD, Open-Meteo, NOAA storm events) and the NCBI/GBIF taxonomy connector validated against `TaxonShape` (SDK-SOURCE-INGEST-R008, SDK-SOURCE-INGEST-R009).
