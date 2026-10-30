# Schema disclosure

The public `scion_sdk.mcp.schema_disclosure` module transports schemas in bounded fragments.
It exports `SchemaManifest`, `SchemaFragment`, `SchemaDisclosure`, `build_schema_disclosure`,
`read_schema_fragment` and `reconstruct_schema`. Producers and consumers use this SDK implementation.
They need no skill checkout at runtime.

The `scion_sdk.mcp.schema_disclosure_provider` module exports
`register_schema_resources(server, catalog, disclosures)` and `describe_schema_tools`.
Use `describe_schema_tools` as the serializer for FastMCP's existing `RegexSearchTransform`.
Attach that transform to the server. Pass the same instance to the resource registrar.
Each read verifies the catalog through its middleware. The visible alias must match the manifest exactly.
Navigation and reads hash the current tool's input and output schemas. Copied metadata cannot authorize stale schemas.
Disabled or unauthorized aliases refuse access, including through guessed URIs.
Requests use the caller's existing MCP session. This API creates no credentials, HTTP clients or separate sessions.

## Wire contract

The manifest URI is:

```text
openapi-schema://v1/{alias}/{schema_sha256}/manifest
```

The fragment URI is:

```text
openapi-schema://v1/{alias}/{schema_sha256}/fragments/{index}
```

Both return one resource body with the `application/json` MIME type.
The index uses decimal digits from zero through `fragment_count - 1`, without signs or leading zeros.

Call `SchemaManifest.model_json_schema()` or `SchemaFragment.model_json_schema()` to read each model's JSON Schema.
The published artifacts are the [manifest schema](reference/schema-manifest.schema.json)
and [fragment schema](reference/schema-fragment.schema.json).
Run `python -m scripts.generate_schema_disclosure --check` to verify the artifacts.
The fragment schema references the manifest's shared identity definition. Load both documents in a JSON Schema registry.
Models reject unknown fields and coercion. A manifest contains these fields:

| Field | Meaning |
|---|---|
| `version` | Integer `1` |
| `operation`, `alias` | Operation ID and registered tool name |
| `source_sha256` | SHA-256 of immutable source bytes |
| `schema_sha256`, `schema_bytes` | Digest and byte length of the complete document |
| `input_schema_sha256`, `output_schema_sha256` | Digests of the input and output schemas |
| `fragment_count` | Number of ordered fragments |
| `manifest_uri`, `fragment_uri_template` | Derived URIs above; the latter retains `{index}` |

Each fragment repeats the manifest and adds `index`, `fragment_sha256` and `text`.
Its digest covers `text.encode("utf-8")`.
The complete document has the form `{"inputSchema": ..., "outputSchema": ...}`.
Encoding uses sorted keys, compact separators, UTF-8 and literal Unicode. It refuses nonfinite numbers.
Each schema's digest uses this encoding. Concatenating fragment text in index order must reproduce the complete document byte-for-byte.

Each fragment contains at most 4,096 UTF-8 bytes without splitting a code point.
Its JSON envelope must fit within 32 KiB. The complete document must fit within 16 MiB.
These bounds govern transport. They do not authorize inserting the complete schema into a model's prompt.
Navigation carries `kind: schema-navigation`. It summarizes a tool and does not replace validation.

## Consumer requirement

Select a manifest through authenticated discovery. Read its manifest URI and all fragment URIs through the same authorized route.
Require exact agreement with the selected manifest, then call `reconstruct_schema(selected_manifest, fragments)`.
Validate arguments and responses against the reconstructed schemas.
Bind the selected identity to caller scope and catalog/child generation before invocation.
A fragment's hash cannot replace the independently selected manifest.

The API refuses stale hashes, mixed operations, malformed indices, incomplete or reordered fragments, corruption and inconsistent schema identities.
Native authorization, write confirmation and source compatibility remain mandatory.
Registering resources does not prove that a consumer has read them. Consumer integration needs separate tests.
