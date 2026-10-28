"""Provider retries and shared rate-limit refusal against live EG."""

import asyncio

from live_engine import live_ingest, scoped_client  # noqa: F401

from agent_connector_sdk.adapters.paper_models import PaperQuery
from agent_connector_sdk.adapters.paper_provider import ProviderFailure, ProviderPage
from agent_connector_sdk.adapters.paper_quota import PaperQuotaPolicy, SharedPaperQuota
from agent_connector_sdk.adapters.paper_search import (
    PaperSearchService,
    ProviderBinding,
)


class RateLimitedProvider:
    def __init__(self, retry_after):
        self.retry_after = retry_after
        self.calls = []

    async def search(self, query, cursor):
        self.calls.append(asyncio.get_running_loop().time())
        if len(self.calls) == 1:
            raise ProviderFailure("rate_limited", retry_after_seconds=self.retry_after)
        return ProviderPage()


async def exercise():
    client = await scoped_client(
        ["kv:read", "kv:write", "kv:shared:read", "kv:shared:write"]
    )
    try:
        quota = SharedPaperQuota(client)
        query = PaperQuery(
            tenant="tenant",
            query="query",
            provider_ids=("provider",),
            schema_revision="v1",
        )

        async def authorize(query, context):
            return True

        provider = RateLimitedProvider(0.05)
        policy = PaperQuotaPolicy(
            provider_id="provider",
            credential_group="retry-test",
            policy_revision="v1",
            minimum_spacing_ns=1,
        )
        service = PaperSearchService(
            {"provider": ProviderBinding(provider, policy)},
            quota=quota,
            authorize=authorize,
        )
        result = await service.search(query, None)
        assert result.completeness == "complete"
        assert len(provider.calls) == 2
        assert provider.calls[1] - provider.calls[0] >= 0.05

        blocked = RateLimitedProvider(None)
        policy = policy.model_copy(update={"credential_group": "unknown-delay-test"})
        service = PaperSearchService(
            {"provider": ProviderBinding(blocked, policy)},
            quota=quota,
            authorize=authorize,
        )
        first = await service.search(query, None)
        second = await service.search(query, None)
        assert first.reports[0].outcome == second.reports[0].outcome == "rate_limited"
        assert len(blocked.calls) == 1
    finally:
        await client.close()


def test_retry_after_and_unknown_delay_fail_closed(live_ingest):  # noqa: F811
    asyncio.run_coroutine_threadsafe(exercise(), live_ingest._loop).result(30)
