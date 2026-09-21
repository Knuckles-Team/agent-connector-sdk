# agent-connector-sdk

[![Build](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/release.yml/badge.svg)](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/release.yml)
[![Documentation](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/pages.yml/badge.svg)](https://knuckles-team.github.io/agent-connector-sdk/)
[![PyPI - Version](https://img.shields.io/pypi/v/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - Downloads](https://img.shields.io/pypi/dd/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - License](https://img.shields.io/pypi/l/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - Wheel](https://img.shields.io/pypi/wheel/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - Implementation](https://img.shields.io/pypi/implementation/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![GitHub Repo stars](https://img.shields.io/github/stars/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/forks)
[![GitHub contributors](https://img.shields.io/github/contributors/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/graphs/contributors)
[![GitHub License](https://img.shields.io/github/license/Knuckles-Team/agent-connector-sdk)](LICENSE)
[![GitHub last commit](https://img.shields.io/github/last-commit/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/commits/main/)
[![GitHub pull requests](https://img.shields.io/github/issues-pr/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/pulls)
[![GitHub closed pull requests](https://img.shields.io/github/issues-pr-closed/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/pulls?q=is%3Apr+is%3Aclosed)
[![GitHub issues](https://img.shields.io/github/issues/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/issues)
[![GitHub top language](https://img.shields.io/github/languages/top/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![GitHub language count](https://img.shields.io/github/languages/count/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![GitHub repo size](https://img.shields.io/github/repo-size/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![GitHub repo file count](https://img.shields.io/github/directory-file-count/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)

Current package — *Version: 0.1.0*

Build secure, discoverable connector servers that expose tools and content over
the Model Context Protocol (MCP), synchronize external sources into
epistemic-graph, and apply governed changes back to those sources.

The SDK gives every connector one consistent runtime contract without coupling
it to an agent framework. Connector packages supply their vendor API client and
domain tools; the SDK supplies the server, policies, lifecycle, extension ports,
and conformance tests.

## Highlights

- **Production MCP servers:** authentication, safe network exposure, health,
  visibility controls, rate limits, change subscriptions, and condensed or
  verbose tool surfaces.
- **Declarative connector content:** publish skills, prompts, ontologies, SHACL
  shapes, and a connector manifest as native MCP primitives.
- **Reliable source synchronization:** discover and extract typed pages through
  entry-point extensions, acknowledge checkpoints only after durable receipts,
  and resume after interruption.
- **Governed write-back:** dry-run exact diffs, verify authorization and source
  versions, preserve idempotency, and reconcile uncertain effects before retry.
- **Connector conformance:** certify extension capabilities, manifest pins,
  pagination behavior, and write-back safety before activation.
- **Governed HTTP clients:** bounded retries, pagination, TLS profiles, secret
  references, RFC 9457 errors, and redacted diagnostics.

## Install

Requires Python 3.12 or newer.

```bash
pip install agent-connector-sdk
```

## Build a connector server

The factory establishes the common server policy. Your package registers its
own API client and domain tools, then starts the selected transport.

```python
import sys
from pathlib import Path

from agent_connector_sdk.mcp.content import ConnectorContent
from agent_connector_sdk.mcp.server import create_mcp_server
from agent_connector_sdk.mcp.tool_surface import register_tool_surface

from demo_connector.api_client import DemoClient
from demo_connector.auth import get_client


def build_server():
    args, mcp, middlewares = create_mcp_server(
        "demo-connector",
        version="1.0.0",
        content=ConnectorContent(
            connector="demo-connector",
            package_root=Path(__file__).parent,
            manifest_path=Path(__file__).parent / "connector_manifest.yml",
        ),
    )
    register_tool_surface(
        mcp,
        service="demo-connector",
        client_cls=DemoClient,
        get_client=get_client,
        tools_module=sys.modules[__name__],
    )
    for middleware in middlewares:
        mcp.add_middleware(middleware)
    return args, mcp
```

`create_mcp_server` refuses unsafe non-loopback exposure. Connector content is
validated before it is served, and malformed visibility filters expose nothing
rather than widening access.

See [Connector servers](https://knuckles-team.github.io/agent-connector-sdk/connector-servers/)
for transports, authentication, tool modes, and deployment policy.

## Synchronize sources

`connector-sync` supervises one or many connector endpoints. Each descriptor
points to a connector package and its MCP endpoint; credentials must be secret
references rather than literal values.

```yaml
settings:
  max_concurrency: 4
connectors:
  - connector: demo-connector
    package_root: ./demo-connector
    endpoint:
      url: https://demo.example/mcp
      bearer_token: env://DEMO_MCP_TOKEN
    interval_seconds: 900
    provision: true
```

```bash
connector-certify ./demo-connector --check -- demo-mcp --transport stdio
connector-sync --config runner.yml --once
connector-sync --config runner.yml --health-addr 127.0.0.1:8765
```

The runner provisions connector content, extracts configured streams, commits
through its selected sink, and advances a cursor only from the sink's receipt.
Its liveness and readiness endpoints report the scheduler and dependency state;
an unavailable sink fails readiness instead of dropping data.

See [Connector sync](https://knuckles-team.github.io/agent-connector-sdk/connector-sync/)
and [Connector certification](https://knuckles-team.github.io/agent-connector-sdk/connector-certify/).

## Architecture and ownership

The SDK owns connector transport and lifecycle behavior. It intentionally does
not become a graph database, an agent harness, or a vendor client.

| Concern | Authority |
|---|---|
| MCP server, source paging, and sync scheduling | `agent-connector-sdk` |
| Vendor transport, revisions, and source effects | the connector |
| Graph records, schemas, reasoning, and receipts | `epistemic-graph` |
| Repository snapshots and file transport | the connector implementation |
| Code parsing, semantic indexing, and index results | `epistemic-graph` |
| Agent goals, workflows, routing, and policy | the agent control plane |

This boundary keeps one authoritative contract: connectors move source data and
effects; epistemic-graph decides how durable graph state is validated, stored,
indexed, and acknowledged.

## Extension points

Extensions are typed protocols discovered through Python entry points:

| Port | Responsibility |
|---|---|
| `SourceAdapter` | discover capabilities and extract a page from one stream |
| `Transport` | open an authenticated session to a connector server |
| `Sink` | commit packs and record batches and return durable receipts |
| `ArtifactKind` | decode a connector content primitive |
| `WriteBackPort` | inspect, preview, apply, and reconcile a source change set |

Use the bundled conformance kit for every implementation. The runtime rejects
uncertified extensions rather than activating a partially compatible connector.

## Documentation

The complete guides live at
[knuckles-team.github.io/agent-connector-sdk](https://knuckles-team.github.io/agent-connector-sdk/):

- [Connector servers](https://knuckles-team.github.io/agent-connector-sdk/connector-servers/)
- [Content over MCP](https://knuckles-team.github.io/agent-connector-sdk/content-over-mcp/)
- [Extension ports](https://knuckles-team.github.io/agent-connector-sdk/extension-ports/)
- [Conformance kit](https://knuckles-team.github.io/agent-connector-sdk/conformance-kit/)
- [HTTP clients and credentials](https://knuckles-team.github.io/agent-connector-sdk/http-clients/)

## Development

```bash
uv sync
uv run --frozen python -m pytest -q
uv run --frozen --only-group docs mkdocs build --strict
pre-commit run --all-files
```

Contributions should preserve the SDK's fail-closed policies, typed boundaries,
and dependency direction. Include focused tests, run the complete gate suite,
and submit the change through a pull request.

## License

Licensed under the [MIT License](LICENSE).
