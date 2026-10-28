"""Shared paper quota coordinates independent clients through real EG KV."""

from __future__ import annotations

import asyncio

import pytest
from live_engine import live_ingest, scoped_client  # noqa: F401

from agent_connector_sdk.adapters.paper_quota import (
    PaperQuotaPolicy,
    QuotaSlot,
    QuotaUnavailable,
    SharedPaperQuota,
)


async def _exercise():
    first_client = await scoped_client(
        ["kv:read", "kv:write", "kv:shared:read", "kv:shared:write"]
    )
    second_client = await scoped_client(
        ["kv:read", "kv:write", "kv:shared:read", "kv:shared:write"]
    )
    try:
        first, second = SharedPaperQuota(first_client), SharedPaperQuota(second_client)
        policy = PaperQuotaPolicy(
            provider_id="provider",
            credential_group="account",
            policy_revision="v1",
            minimum_spacing_ns=1,
        )
        async with first.request_slot(policy):
            with pytest.raises(QuotaUnavailable, match="busy"):
                async with second.request_slot(
                    policy.model_copy(update={"provider_id": "other-provider"})
                ):
                    raise AssertionError("second client entered an active slot")
        async with second.request_slot(policy):
            pass
        with pytest.raises(QuotaUnavailable, match="policy_mismatch"):
            async with first.request_slot(
                policy.model_copy(update={"minimum_spacing_ns": 2})
            ):
                raise AssertionError("a different policy entered the slot")
        async with first.request_slot(policy) as slot:
            assert isinstance(slot, QuotaSlot)
            slot.retain()
        with pytest.raises(QuotaUnavailable, match="busy"):
            async with second.request_slot(policy):
                raise AssertionError("retained rate limit was released")
    finally:
        await first_client.close()
        await second_client.close()


def test_shared_quota_is_exclusive_and_binds_policy(live_ingest):  # noqa: F811
    asyncio.run_coroutine_threadsafe(_exercise(), live_ingest._loop).result(30)
