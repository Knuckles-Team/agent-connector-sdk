# Credentials

Manifests, configuration, packs and records carry secret references, never
values. References are resolved in memory where a connector starts.

## Reference forms

| Form | Resolves to |
|---|---|
| `env://NAME` | the environment variable `NAME` |
| `openbao://<mount>/<path>#<field>` | the field of the OpenBao KV v2 secret at `<mount>/<path>` |
| `openbao://<mount>/<path>#<field>@<version>` | the same field at an exact version |

For example, `openbao://apps/freshrss-agent#FRESHRSS_TOKEN`.

## Resolvers

| Resolver | Module |
|---|---|
| `EnvironmentCredentialResolver` | `credentials.resolver` |
| `OpenBaoCredentialResolver` | `credentials.openbao` |
| `CompositeCredentialResolver` | `credentials.resolver` |
| `default_credential_resolver()` | `credentials.resolution` |

`OpenBaoCredentialResolver.from_settings()` reads `OPENBAO_ADDR`,
`OPENBAO_NAMESPACE` and `OPENBAO_TOKEN_REF`. The token reference must be
`env://`, because the token that unlocks OpenBao cannot itself be stored there.
HTTPS is required outside loopback. With `OPENBAO_ADDR` set and
`OPENBAO_TOKEN_REF` unset or blank, `default_credential_resolver()` adds no
OpenBao resolver and serves `env://` references from the environment.

## Configuration files

The shared Arbora platform configuration (`workspace.yml`, `config.json`,
`mcp_config.json`, ...) lives in `$XDG_CONFIG_HOME/arbora` (`~/.config/arbora`),
overridable with `ARBORA_CONFIG_DIR`. Resolve it with
`agent_connector_sdk.paths.platform_config_dir()` or `platform_config_file(name)`.
There is no fallback to the pre-rename `graph-os` or `agent-utilities` locations.

`load_config()` projects `$XDG_CONFIG_HOME/agent-connector-sdk/config.json` (or
`CONNECTOR_CONFIG_FILE`) into the environment without overriding variables that
are already set. A credential-shaped key (`*_SECRET`, `*_PASSWORD`, `*_TOKEN`,
`*_API_KEY`, `*_PRIVATE_KEY`) must hold a reference; a plain value is an error.
