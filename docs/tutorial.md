# Build your first connector

This tutorial creates one MCP server in one Python file, runs it safely on
loopback, and verifies an observable SDK health response. It uses the same
server factory and tool-surface registration path as a packaged connector.

## 1. Create the project

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv init --bare demo-connector
cd demo-connector
uv add agent-connector-sdk
```

## 2. Add the connector

Create `connector.py`:

```python
from typing import Literal

from agent_connector_sdk.mcp.server import create_mcp_server
from agent_connector_sdk.mcp.tool_surface import register_tool_surface


def register_status_tools(server) -> None:
    @server.tool
    async def demo(action: Literal["ping"] = "ping") -> dict[str, str]:
        """Return the connector's observable status."""
        return {
            "action": action,
            "connector": "demo",
            "status": "ok",
        }


def main() -> None:
    args, server, middlewares = create_mcp_server(
        "demo-connector",
        version="0.1.0",
        instructions="A minimal observable connector.",
    )
    register_tool_surface(
        server,
        service="demo-connector",
        registrars=[register_status_tools],
    )
    for middleware in middlewares:
        server.add_middleware(middleware)

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

`create_mcp_server` installs the common health route, visibility transform,
change-subscription surface, authentication policy, and middleware. The tool
registrar goes through `register_tool_surface`, so SDK tool modes and per-domain
toggles apply consistently.

## 3. Run and observe it

Start a loopback-only streamable HTTP server:

```bash
uv run python connector.py --transport streamable-http \
  --host 127.0.0.1 --port 8000
```

From another terminal, read the health contract:

```bash
curl -s http://127.0.0.1:8000/health
```

The response is:

```json
{"status":"ok"}
```

Loopback works without external authentication. An exposed listener is accepted
only with the SDK's authentication, TLS-boundary, and allowed-host policies.

## 4. Package connector content

A production connector can publish content beside its server:

```text
demo_connector/
├── connector_manifest.yml
├── ontology/
│   ├── demo.ttl
│   └── shapes/
│       └── demo-shapes.ttl
├── prompts/
│   └── investigate.json
└── skills/
    └── demo-operations/
        └── SKILL.md
```

Pass a `ConnectorContent` to `create_mcp_server` to expose those files as MCP
skills, prompts, and resources. Content validation fails closed when a declared
file is missing or malformed.

## 5. Certify the tool contract

Connector sync pins the live input and output schemas returned by `tools/list`.
Once the project has its manifest and presets, certify the running server:

```bash
connector-certify . --check \
  -- uv run python connector.py --transport stdio
```

Certification lists tools without invoking them or reaching the vendor API. Use
`--write` only when intentionally refreshing reviewed fingerprint files.

## 6. Join the source lifecycle

Durable source sync is composed by GraphOS with a verified epistemic-graph
client and current ConnectorPack authority. The SDK discovers and extracts
source pages; generated epistemic-graph requests own mapping, checkpoint CAS,
provenance, and durable receipts.

Continue with:

- [Architecture](architecture.md) for the complete SourceIngest, ConnectorPack,
  and WriteBack lifecycles.
- [Connector servers](connector-servers.md) for authentication and exposure.
- [Content over MCP](content-over-mcp.md) for manifests and content identity.
- [Connector sync](connector-sync.md) for supervised source operation.
- [Conformance kit](conformance-kit.md) before publishing an extension.
