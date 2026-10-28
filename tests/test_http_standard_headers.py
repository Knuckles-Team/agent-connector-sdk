"""Standard headers and case-insensitive caller overrides."""

import httpx
import pytest

from agent_connector_sdk.http.client import create_http_client, standard_headers
from agent_connector_sdk.http.options import HttpClientOptions


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R780.8")
def test_standard_headers_and_case_insensitive_override():
    assert standard_headers()["User-Agent"].startswith("agent-connector-sdk/")
    observed = []
    transport = httpx.MockTransport(
        lambda request: (
            observed.append(request.headers.get_list("user-agent"))
            or httpx.Response(200)
        )
    )
    options = HttpClientOptions(
        base_url="https://example.com", headers={"user-agent": "consumer/1"}
    )
    with create_http_client(options, transport=transport) as client:
        assert client.get("/").status_code == 200
    assert observed == [["consumer/1"]]
