"""EVM models retain exact values and refuse unimplemented extraction."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent_connector_sdk.adapters.event_envelope import FeedKind
from agent_connector_sdk.adapters.event_feed import EventFeedSourceAdapter
from agent_connector_sdk.adapters.evm_chain import EvmLogDescriptor, EvmTrade
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import SourceContractError

ADDRESS = "0x" + "a" * 40
HASH = "0x" + "b" * 64


def descriptor(**changes):
    values = {
        "chain_id": 1,
        "contract": ADDRESS,
        "event_signature": HASH,
        "decoder_revision": "v1",
        "first_block": 0,
        "last_block": 100,
    }
    return EvmLogDescriptor.model_validate({**values, **changes})


def trade(**changes):
    values = {
        "chain_id": 1,
        "contract": ADDRESS,
        "event_signature": HASH,
        "decoder_revision": "v1",
        "transaction_hash": HASH,
        "block_hash": HASH,
        "block_number": 2,
        "log_index": 1,
        "asset_in": ADDRESS,
        "asset_out": ADDRESS,
        "amount_in": 2**200 + 1,
        "amount_out": 42,
        "scale_in": 18,
        "scale_out": 6,
        "side": "buy",
    }
    return EvmTrade.model_validate({**values, **changes})


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.47")
def test_evm_models_validate_identity_and_exact_numbers() -> None:
    value = trade()
    assert value.amount_in == 2**200 + 1
    assert trade(amount_in=0).amount_in == 0
    assert descriptor().last_block == 100
    for changes in (
        {"chain_id": 0},
        {"contract": "bad"},
        {"contract": ADDRESS + "\n"},
        {"event_signature": "bad"},
        {"event_signature": HASH + "\n"},
        {"decoder_revision": ""},
        {"last_block": -1},
        {"first_block": 101},
    ):
        with pytest.raises(ValidationError):
            descriptor(**changes)
    for changes in (
        {"amount_in": 1.0},
        {"amount_in": True},
        {"amount_in": 2**256},
        {"scale_in": 256},
        {"transaction_hash": "bad"},
        {"log_index": -1},
        {"side": "unknown"},
    ):
        with pytest.raises(ValidationError):
            trade(**changes)
    with pytest.raises(ValidationError):
        value.amount_in = 1


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.47")
@pytest.mark.asyncio
async def test_evm_descriptor_refuses_undecoded_extraction() -> None:
    preset = ToolPreset(name="chain", server="server", tool="logs", id_field="id")
    adapter = EventFeedSourceAdapter(
        preset,
        feed_kind=FeedKind.RUM,
        connector="example",
        tool_schema_sha256="pin",
        mapping_reference="map",
        chain_descriptor=descriptor(),
    )
    assert adapter.chain_descriptor == descriptor()
    with pytest.raises(
        SourceContractError, match="chain-log decoding is not available"
    ):
        await adapter.discover(SimpleNamespace())
    with pytest.raises(
        SourceContractError, match="chain-log decoding is not available"
    ):
        await adapter.extract(SimpleNamespace(), None)
