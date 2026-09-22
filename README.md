# Agent Connector SDK

<p align="center">
  <img src="docs/assets/brands/agent-connector-sdk-logo-v1.png" alt="Agent Connector SDK logo" width="160" />
</p>

[![PyPI - Version](https://img.shields.io/pypi/v/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![Build](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/release.yml/badge.svg)](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/release.yml)
[![Documentation](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/pages.yml/badge.svg)](https://knuckles-team.github.io/agent-connector-sdk/)

<details>
<summary>Project telemetry</summary>

[![GitHub Repo stars](https://img.shields.io/github/stars/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/forks)
[![GitHub contributors](https://img.shields.io/github/contributors/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/graphs/contributors)
[![GitHub license](https://img.shields.io/github/license/Knuckles-Team/agent-connector-sdk)](LICENSE)
[![GitHub last commit (by committer)](https://img.shields.io/github/last-commit/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/commits/main)
[![GitHub pull requests](https://img.shields.io/github/issues-pr/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/pulls)
[![GitHub closed pull requests](https://img.shields.io/github/issues-pr-closed/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/pulls?q=is%3Apr+is%3Aclosed)
[![GitHub issues](https://img.shields.io/github/issues/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/issues)
[![GitHub top language](https://img.shields.io/github/languages/top/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![GitHub language count](https://img.shields.io/github/languages/count/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![GitHub repo size](https://img.shields.io/github/repo-size/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![GitHub repo file count (file type)](https://img.shields.io/github/directory-file-count/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![PyPI - Downloads](https://img.shields.io/pypi/dd/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - License](https://img.shields.io/pypi/l/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - Wheel](https://img.shields.io/pypi/wheel/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - Implementation](https://img.shields.io/pypi/implementation/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)

</details>

## Overview

Agent Connector SDK is the ecosystem's source integration boundary. It turns
vendor APIs and domain tools into secure MCP connectors, synchronizes bounded
source records into Epistemic Graph, and applies authorized changes back to the
source. Connector packages keep vendor behavior; generated Epistemic Graph
contracts own durable records, receipts, and graph state.

Package version: 0.1.0.

## Key capabilities

- Build FastMCP servers with authentication, safe exposure, health, visibility,
  rate limits, change subscriptions, and condensed or verbose tool surfaces.
- Publish skills, prompts, ontologies, SHACL shapes, and connector manifests as
  typed MCP content.
- Extract bounded source pages and advance checkpoints only from matching
  durable receipts created by Epistemic Graph.
- Import deterministic ConnectorPack archives with exact content identity and
  generated Epistemic Graph contracts.
- Govern write-back through dry-run, authorization, source-version checks,
  idempotency, and uncertain-effect reconciliation.
- Certify extension identity, MCP schemas, pagination, and safety behavior before
  activation.

## Documentation

Start with the
[one-file connector tutorial](https://knuckles-team.github.io/agent-connector-sdk/tutorial/),
then use the [architecture guide](https://knuckles-team.github.io/agent-connector-sdk/architecture/)
for SourceIngest, ConnectorPack, and WriteBack lifecycles.

- [Documentation home](https://knuckles-team.github.io/agent-connector-sdk/)
- [Connector server reference](https://knuckles-team.github.io/agent-connector-sdk/connector-servers/)
- [Source synchronization](https://knuckles-team.github.io/agent-connector-sdk/connector-sync/)
- [Extension ports and conformance](https://knuckles-team.github.io/agent-connector-sdk/extension-ports/)
- [Epistemic Graph](https://knuckles-team.github.io/epistemic-graph/) — durable graph and contract authority
- [Graph OS](https://knuckles-team.github.io/graph-os/) — authenticated runtime composition
- [Build status](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/release.yml)

## Architecture

![Runtime architecture: people use Agent Web UI, Agent Terminal UI, Geniusbot, and Graph OS-hosted messaging; MCP, REST, and A2A clients enter through Graph OS; source systems flow through Agent Connector SDK into Epistemic Graph.](docs/assets/runtime-architecture.svg)

People enter the platform through [Agent Web UI](https://knuckles-team.github.io/agent-webui/),
[Agent Terminal UI](https://knuckles-team.github.io/agent-terminal-ui/),
[Geniusbot](https://knuckles-team.github.io/geniusbot/), or Graph OS-hosted messaging.
Agent Terminal UI exposes REST operations; it has no ACP conversational path.
MCP, REST, and A2A clients also enter through [Graph OS](https://knuckles-team.github.io/graph-os/),
which routes agent work to [Agent Utilities](https://knuckles-team.github.io/agent-utilities/)
and durable knowledge to [Epistemic Graph](https://knuckles-team.github.io/epistemic-graph/).
External sources connect through this SDK into Epistemic Graph.

| The SDK owns | The SDK does not own |
|---|---|
| MCP server lifecycle and security | vendor API models and business semantics |
| source transport, bounded paging, and certification | Epistemic Graph's durable records, schemas, reasoning, and receipts |
| connector content capture and deterministic handoff | agent goals, model calls, workflow routing, or deployment policy |
| governed source-side write-back execution | authorization policy or graph-side change-set authority |

The SDK depends directly on `epistemic-graph>=2.27.0`. Its generated
SourceIngest, ConnectorPack, and WriteBack models and clients are the sole
graph-boundary contracts; the SDK defines no parallel DTO, receipt, or digest.
The bundled sink reads Epistemic Graph's durable source status, commits record
pages, and imports independently identified connector content packs through
those APIs.

## Quick start

Create a project and install the SDK:

```bash
uv init --bare demo-connector
cd demo-connector
uv add agent-connector-sdk
uv sync
```

Save this as `connector.py`:

```python
from typing import Literal

from agent_connector_sdk.mcp.server import create_mcp_server

args, mcp, middlewares = create_mcp_server(
    "demo-connector",
    version="0.1.0",
    instructions="A minimal observable connector.",
)


@mcp.tool
async def demo(action: Literal["ping"] = "ping") -> dict[str, str]:
    """Check that the connector tool surface is responding."""
    return {"connector": "demo", "status": "ok", "action": action}


for middleware in middlewares:
    mcp.add_middleware(middleware)

if args.transport == "stdio":
    mcp.run(transport="stdio")
else:
    mcp.run(transport=args.transport, host=args.host, port=args.port)
```

Run it on loopback and observe the SDK health contract:

```bash
uv run python connector.py --transport streamable-http \
  --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health
```

The health endpoint returns `{"status":"ok"}`.

The [tutorial](https://knuckles-team.github.io/agent-connector-sdk/tutorial/)
adds tool-surface registration, declarative content, certification, and source
sync without changing this server foundation.

## Contributing

Issues and pull requests are welcome. Follow [AGENTS.md](AGENTS.md) for ownership,
isolation, and validation rules. Run the tests and public documentation gate
before submitting a change.

## License

Licensed under the [MIT License](LICENSE).
