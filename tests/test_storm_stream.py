import gzip

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from storm_test_helpers import archive_policy

from agent_connector_sdk.earth_observations.storm import (
    NoaaStormArchive,
    StormAdmission,
)
from agent_connector_sdk.earth_observations.storm_stream import register_storm_stream


@pytest.mark.asyncio
async def test_storm_authorizes_before_archive_access(tmp_path):
    body = b"BEGIN_YEARMONTH,BEGIN_DAY,BEGIN_TIME,EPISODE_ID,EVENT_ID,CZ_TIMEZONE,EVENT_TYPE\n202503,1,1630,22,33,CST-6,Tornado\n"
    compressed = gzip.compress(body)
    (tmp_path / "source.csv.gz").write_bytes(compressed)
    policy = archive_policy(tmp_path, compressed)
    admissions = []

    def admit(row):
        admissions.append(row["EVENT_ID"])
        return StormAdmission("noaa:22", "Episode 22", "place", "EF1")

    allowed = False

    async def authorize(tenant, ctx):
        return allowed and tenant == "tenant"

    mcp = FastMCP("storm")
    register_storm_stream(
        mcp,
        NoaaStormArchive(policy, admit),
        ["33"],
        tenant="tenant",
        name="storm",
        connector="storm",
        batch_size=1,
        policy_revision="v1",
        authorize=authorize,
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("storm", {})
        assert not admissions
        allowed = True
        result = (await client.call_tool("storm", {})).structured_content
        assert admissions == ["33"]
        assert {item["node_type"] for item in result["records"]} == {
            "WeatherEvent",
            "WeatherSystem",
        }
        assert result["relationships"] == [
            {
                "source": "event:33",
                "target": "system:noaa:22",
                "relationship": "occursIn",
            }
        ]
