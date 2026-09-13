# agent-connector-sdk

*Version: 0.1.0*

The connector SDK for the agent-packages fleet. A connector built on it serves its
tools, skills, prompts, ontologies, shapes and manifest as native MCP primitives,
and its sources are extracted through typed, entry-point-discovered ports.

It depends on `fastmcp` and the `epistemic_graph` client only, never on
agent-utilities (RF-ADR-009: the SDK is phase 3 of the workspace order).

## Install

```bash
pip install agent-connector-sdk
```

## A connector server

```python
from pathlib import Path

from agent_connector_sdk.config import load_config
from agent_connector_sdk.mcp.content import ConnectorContent
from agent_connector_sdk.mcp.server import create_mcp_server
from agent_connector_sdk.mcp.tool_surface import register_tool_surface

load_config()
args, mcp, middlewares = create_mcp_server(
    "demo-mcp",
    version="1.0.0",
    content=ConnectorContent(connector="demo-agent", package_root=Path(__file__).parent),
)
register_tool_surface(mcp, service="demo-agent", tools_module=my_tools)
for middleware in middlewares:
    mcp.add_middleware(middleware)
```

## Extracting a source

```python
from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport

adapter = McpToolSourceAdapter.from_sync_spec(manifest.sync[0], connector="demo-agent")
async with McpTransport().session(TransportEndpoint(url="https://demo.example/mcp")) as session:
    await adapter.discover(session)
    page = await adapter.extract(session, cursor=None)
```

Documentation: <https://knuckles-team.github.io/agent-connector-sdk/>.

Records are handed to a `Sink`. The epistemic-graph sink is a declared contract
seam until epistemic-graph publishes its pack-import and ingestion methods
(RF-ADR-009 wave W1); calling it raises `NotImplementedError`.
