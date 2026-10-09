# Fleet connector migration evidence (2026-10-09)

Per-connector merged pull requests migrating each package off `agent_utilities`
onto `agent_connector_sdk`, grouped by the alphabetical batch requirement each
connector package name falls into. Batches are assigned by the first letter of
the connector repository name, per `spec.md`'s batch definition: A-E
(SDK-CONNECTOR-CONTROL-R009), F-J (SDK-CONNECTOR-CONTROL-R010), K-O
(SDK-CONNECTOR-CONTROL-R011), P-S (SDK-CONNECTOR-CONTROL-R012), T-Z
(SDK-CONNECTOR-CONTROL-R013). Each row's commit is the merge commit of the
named pull request in that connector's own public repository; the connector
package owns its migration commit, per the spec's text. This table is informational
fleet-consumer evidence recorded by the SDK repository; it is not a substitute for
a per-package `scan_for_agent_utilities_imports` run, which remains open work.

Total connectors migrated: 69.

## SDK-CONNECTOR-CONTROL-R009 (batch A-E, 19 connectors)

| Connector | PR | Merge commit |
|---|---|---|
| `ansible-tower-mcp` | [#6](https://github.com/Knuckles-Team/ansible-tower-mcp/pull/6) | `889660fc92db3d88633f75f71c1cc443bef87f6e` |
| `archimate-mcp` | [#4](https://github.com/Knuckles-Team/archimate-mcp/pull/4) | `5e0154272c18f28431c1e616176bbd7833dc5c03` |
| `archivebox-api` | [#8](https://github.com/Knuckles-Team/archivebox-api/pull/8) | `39fe1cf92addccf00fcf0d130cd9957703cab489` |
| `aris-mcp` | [#2](https://github.com/Knuckles-Team/aris-mcp/pull/2) | `b675980f7fb16ad8b405c6b57427fe179e1ffe78` |
| `arr-mcp` | [#12](https://github.com/Knuckles-Team/arr-mcp/pull/12) | `180ee4b2620ebc59ad36b57538560ba582119894` |
| `atlassian-agent` | [#5](https://github.com/Knuckles-Team/atlassian-agent/pull/5) | `b76dae74d1263fbcd23bf7235087d9c83fb603f0` |
| `audio-transcriber` | [#8](https://github.com/Knuckles-Team/audio-transcriber/pull/8) | `55124d5d80518c601654df5b1234ce567e307305` |
| `audiobookshelf-mcp` | [#5](https://github.com/Knuckles-Team/audiobookshelf-mcp/pull/5) | `2dbe3377d12c6e20854adf5e8572785d71d69f46` |
| `caddy-mcp` | [#4](https://github.com/Knuckles-Team/caddy-mcp/pull/4) | `623c952ae9202065f75e72dead93dd0ed1bc6c3a` |
| `camunda-mcp` | [#4](https://github.com/Knuckles-Team/camunda-mcp/pull/4) | `989dfe4996240e10e9cf71788c05c7255ae6eb36` |
| `ciso-assistant-api` | [#5](https://github.com/Knuckles-Team/ciso-assistant-api/pull/5) | `2db26dc5b49330929ae6d48506a805c7756d01e6` |
| `clarity-api` | [#5](https://github.com/Knuckles-Team/clarity-api/pull/5) | `06b3b3cae2556bab5480062ed00cd3e759d14ded` |
| `container-manager-mcp` | [#10](https://github.com/Knuckles-Team/container-manager-mcp/pull/10) | `9c05eee8f0a6aef3f9c466ff0eceffc4acea4da8` |
| `data-science-mcp` | [#4](https://github.com/Knuckles-Team/data-science-mcp/pull/4) | `08416588eace87b475398e14af3190c9b62be37a` |
| `dockerhub-api` | [#5](https://github.com/Knuckles-Team/dockerhub-api/pull/5) | `414a05d2e60f5cf3565a982673df9709cf78036d` |
| `documentdb-mcp` | [#6](https://github.com/Knuckles-Team/documentdb-mcp/pull/6) | `f5e7f0f585dce0c37fc26f644b009706701d10d7` |
| `egeria-mcp` | [#4](https://github.com/Knuckles-Team/egeria-mcp/pull/4) | `bc05f6743b37e4a0df398390a6adda8d5fa13245` |
| `emerald-exchange` | [#6](https://github.com/Knuckles-Team/emerald-exchange/pull/6) | `4a575925d1e317fa724698fb5a4d589e2048e994` |
| `erpnext-agent` | [#5](https://github.com/Knuckles-Team/erpnext-agent/pull/5) | `0c8ddfce2aa8b1f8b0989b8cd092ac787142c3ce` |

## SDK-CONNECTOR-CONTROL-R010 (batch F-J, 10 connectors)

| Connector | PR | Merge commit |
|---|---|---|
| `fan-manager` | [#5](https://github.com/Knuckles-Team/fan-manager/pull/5) | `b726413efddfe1d9604836037f99ea8820b03a09` |
| `firefly-iii-mcp` | [#5](https://github.com/Knuckles-Team/firefly-iii-mcp/pull/5) | `401f59b9c357ecd3d0934cf155710ca16fcaf201` |
| `freshrss-agent` | [#2](https://github.com/Knuckles-Team/freshrss-agent/pull/2) | `e7569dfd26b916a11c5de0a6a0bbab3e202d83e8` |
| `github-agent` | [#5](https://github.com/Knuckles-Team/github-agent/pull/5) | `b8d5ccfd7e71c3153a6bd8f7ed5470144d926cbc` |
| `gitlab-api` | [#13](https://github.com/Knuckles-Team/gitlab-api/pull/13) | `a5c1e4822801a369f532b958ce43c502ef8f1942` |
| `gramps-mcp` | [#8](https://github.com/Knuckles-Team/gramps-mcp/pull/8) | `d0ed578d133e4c16cd72ae43c506ac70520ebe88` |
| `hdhomerun-mcp` | [#4](https://github.com/Knuckles-Team/hdhomerun-mcp/pull/4) | `45507a795bc9bb3b3baf872358b144ab93e86714` |
| `home-assistant-agent` | [#4](https://github.com/Knuckles-Team/home-assistant-agent/pull/4) | `131d1fbf2d419dbaf601bfd2de47e003ddd38555` |
| `jellyfin-mcp` | [#6](https://github.com/Knuckles-Team/jellyfin-mcp/pull/6) | `0767cc9f57e5c0307061901abd954d993d599a5a` |
| `jena-mcp` | [#4](https://github.com/Knuckles-Team/jena-mcp/pull/4) | `2e4e910edf99b523aa0ffc284c85ea6d4f5bd31e` |

## SDK-CONNECTOR-CONTROL-R011 (batch K-O, 19 connectors)

| Connector | PR | Merge commit |
|---|---|---|
| `kafka-mcp` | [#6](https://github.com/Knuckles-Team/kafka-mcp/pull/6) | `a0ed641396b0b5420d69dfe248aa1b2e304d51b1` |
| `keycloak-agent` | [#4](https://github.com/Knuckles-Team/keycloak-agent/pull/4) | `b2639e8e0e5fb3eb58b306113af64893eef6119c` |
| `lakekeeper-mcp` | [#2](https://github.com/Knuckles-Team/lakekeeper-mcp/pull/2) | `9d5e64e847aafce4e71ec6fe47900c889acc1e1d` |
| `langfuse-agent` | [#6](https://github.com/Knuckles-Team/langfuse-agent/pull/6) | `f6a718bec928d0d29cf3ebcb2ba887b8d6bc1b42` |
| `leanix-agent` | [#4](https://github.com/Knuckles-Team/leanix-agent/pull/4) | `c8108c00d6025ffc33e0c06b2d48b5bbf2a9dcda` |
| `legal-peripherals-mcp` | [#4](https://github.com/Knuckles-Team/legal-peripherals-mcp/pull/4) | `d2d24d1d25d783bc8bb4f4148d975eccf9c2e0d2` |
| `lgtm-mcp` | [#4](https://github.com/Knuckles-Team/lgtm-mcp/pull/4) | `a96ba86612e020c91b9cb43704dc499f31598647` |
| `listmonk-api` | [#9](https://github.com/Knuckles-Team/listmonk-api/pull/9) | `72f09da58ca77857f3ac2ad43027677d29b54076` |
| `mattermost-mcp` | [#5](https://github.com/Knuckles-Team/mattermost-mcp/pull/5) | `4e34926829340b81e7eb59af1b5f071222371a22` |
| `mealie-mcp` | [#8](https://github.com/Knuckles-Team/mealie-mcp/pull/8) | `6648f52568a05d26d6e2d63461b132ed8789e19f` |
| `media-downloader` | [#6](https://github.com/Knuckles-Team/media-downloader/pull/6) | `707785dd3d019e064b28e9702bfd205960f7ae70` |
| `microsoft-agent` | [#5](https://github.com/Knuckles-Team/microsoft-agent/pull/5) | `505e2bfff75756d7625629501d4356a32839ab00` |
| `nextcloud-agent` | [#5](https://github.com/Knuckles-Team/nextcloud-agent/pull/5) | `92e52bb83d86069a5719f0b9b43abaadb563e027` |
| `objectstore-mcp` | [#5](https://github.com/Knuckles-Team/objectstore-mcp/pull/5) | `2825b299b7118bd1845a14d55e0020914a84b707` |
| `okta-agent` | [#5](https://github.com/Knuckles-Team/okta-agent/pull/5) | `adaae9e31adaf7fa68bf21d2db91db17463eec21` |
| `onetrust-api` | [#5](https://github.com/Knuckles-Team/onetrust-api/pull/5) | `3323878aeca68052e55601bde5115be84ed903e4` |
| `openbao-mcp` | [#6](https://github.com/Knuckles-Team/openbao-mcp/pull/6) | `795c09f183a8e870b1831a16c0560f1561011083` |
| `opensearch-mcp` | [#2](https://github.com/Knuckles-Team/opensearch-mcp/pull/2) | `2aa0b1f7549274ab6314361109e4c0606e8c2757` |
| `owncast-agent` | [#5](https://github.com/Knuckles-Team/owncast-agent/pull/5) | `a5e10b35b167d2930c6b11c8ac6f0e7782c2dcc6` |

## SDK-CONNECTOR-CONTROL-R012 (batch P-S, 15 connectors)

| Connector | PR | Merge commit |
|---|---|---|
| `paperless-ngx-mcp` | [#4](https://github.com/Knuckles-Team/paperless-ngx-mcp/pull/4) | `7ded81d89de848d9a4bc5df0703da8ecde63536e` |
| `plane-agent` | [#5](https://github.com/Knuckles-Team/plane-agent/pull/5) | `8c7164dc310fd4540c6cd8b38dbad4300ed6ddfa` |
| `portainer-agent` | [#5](https://github.com/Knuckles-Team/portainer-agent/pull/5) | `e4d171e0acc2f8a011bf9aef78975d4e70161f3e` |
| `postiz-agent` | [#6](https://github.com/Knuckles-Team/postiz-agent/pull/6) | `890ebf8c31b5ce5c0d2c1af256153be6d31c6fdc` |
| `pulselink-mcp` | [#5](https://github.com/Knuckles-Team/pulselink-mcp/pull/5) | `2b8355f15710e1837a8440521bbf23ea7e784426` |
| `qbittorrent-agent` | [#6](https://github.com/Knuckles-Team/qbittorrent-agent/pull/6) | `f692d14570ff536d126aba06b8e592631f8ae473` |
| `rom-manager` | [#5](https://github.com/Knuckles-Team/rom-manager/pull/5) | `7d533b37d9d21a07944e086838b784904f6df1fb` |
| `salesforce-agent` | [#6](https://github.com/Knuckles-Team/salesforce-agent/pull/6) | `011f0e012673ed573d0500c76e51c8d8eb447eb3` |
| `scholarx` | [#5](https://github.com/Knuckles-Team/scholarx/pull/5) | `84449a4aa897c38fb9b943b52ef1d4101305a3bf` |
| `searxng-mcp` | [#10](https://github.com/Knuckles-Team/searxng-mcp/pull/10) | `629a67c2f065c543ce567e7e8a08a7fd4436c0a1` |
| `servicenow-api` | [#20](https://github.com/Knuckles-Team/servicenow-api/pull/20) | `16c8f0b0dbb3b14c927e981227579eabb8b6f6ac` |
| `spark-mcp` | [#2](https://github.com/Knuckles-Team/spark-mcp/pull/2) | `6bc843581053741a926003900f8f0ab15829164c` |
| `sql-mcp` | [#5](https://github.com/Knuckles-Team/sql-mcp/pull/5) | `d2dd6565cab65f10caac1fc5a918eeda17c181ca` |
| `stirlingpdf-agent` | [#5](https://github.com/Knuckles-Team/stirlingpdf-agent/pull/5) | `1a13f65b7940159af010ba2e1265c776ce7109cc` |
| `systems-manager` | [#6](https://github.com/Knuckles-Team/systems-manager/pull/6) | `45ac1db3794d64fac77e1acaa74bb42ec8c50ee2` |

## SDK-CONNECTOR-CONTROL-R013 (batch T-Z, 6 connectors)

| Connector | PR | Merge commit |
|---|---|---|
| `technitium-dns-mcp` | [#10](https://github.com/Knuckles-Team/technitium-dns-mcp/pull/10) | `fb2cb3341ebc7f5426dbe70bdea06f61169141c9` |
| `tunnel-manager` | [#9](https://github.com/Knuckles-Team/tunnel-manager/pull/9) | `609256b6cc8efb2af6e2bf5d88302a2ddd467996` |
| `twenty-mcp` | [#4](https://github.com/Knuckles-Team/twenty-mcp/pull/4) | `0104b0e3ed6a51fcded3029b1270f766163179bd` |
| `uptime-kuma-agent` | [#5](https://github.com/Knuckles-Team/uptime-kuma-agent/pull/5) | `34185d1c4cffb59dec1341bac71d95ce6f7a1274` |
| `vector-mcp` | [#8](https://github.com/Knuckles-Team/vector-mcp/pull/8) | `699cb005a0b2062a187b4c510af4daab727cd7b3` |
| `wger-agent` | [#6](https://github.com/Knuckles-Team/wger-agent/pull/6) | `c1b75c9243555ab24ce796a3f8fdd3cbc32cf744` |

