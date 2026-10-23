# Connector certification

`connector-certify` reads a connector's declaration from the resource
`connector://resources`. It checks every MCP tool the sync presets use against
the contract that `tools/list` returns. It lists tools only. It never calls a
tool and never reaches the connector's upstream API. It writes no file.

<div class="admonition architecture" markdown>
<p class="admonition-title">Certification flow</p>

The live MCP server serves its declaration and its `tools/list` response. Action-schema
validation checks each declared preset tool and produces the canonical
input/output contract and its SHA-256 fingerprint. The report lists the
fingerprint of each tool.

</div>

## Contract fingerprint

The fingerprint algorithm label is
`agent-connector-sdk:mcp-tool-contract-compat:v2`. Its digest binds the tool
name, canonical input schema and canonical output schema. Object keys are
sorted; string lists such as `required` and `enum` are sorted; presentation
fields (`title`, `description`, `examples`, `$comment`) and runtime defaults are
removed. Output-schema changes therefore change the fingerprint that
`connector-sync` reads at discovery.

An empty input schema is refused. If a preset selects an action, the tool's
action property must constrain that value with JSON Schema `enum`, or with
`const` for a single action. Action names in prose do not certify a callable
contract. A preset with `params_style: json` also requires its configured
`params_arg` property as a string.

## Run it

Start a connector over stdio by putting its command after `--`:

```bash
connector-certify -- sample-mcp --transport stdio
```

`--placeholder NAME` gives a stdio child a fixed non-secret placeholder.
`--env NAME=REFERENCE` resolves an `env://` or `openbao://` reference into the
child environment. These options exist for servers that need configuration to
start; tool listing must not require a real upstream credential.

For a deployed streamable-HTTP server, use a bearer-token reference or OIDC
client credentials:

```bash
connector-certify \
  --url https://sample-mcp.example.invalid/mcp \
  --oidc-token-url https://identity.example.invalid/token \
  --oidc-client-id connector-certify \
  --oidc-client-secret-ref openbao://apps/connector-certify#OIDC_CLIENT_SECRET \
  --oidc-audience agent-services \
  --oidc-scope mcp:tools
```

`--oidc-issuer` may replace `--oidc-token-url`; the SDK discovers the issuer's
token endpoint. The SDK's governed HTTP client obtains and caches the token,
refreshes it before expiry, and retries once with a new token after a 401. The
secret stays a reference until token minting.

`--report PATH` writes a JSON report containing connector and server identity,
the live fingerprint of each tool, a separately visible output-schema
digest, and any defect. It does not include endpoint URLs or credentials.

| Exit | Meaning |
|---|---|
| `0` | every declared preset tool is listed and valid |
| `1` | a declared tool is missing or has an invalid contract |
| `2` | the server can not list its tools or its declaration |
