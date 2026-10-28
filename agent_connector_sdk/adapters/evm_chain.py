"""Typed EVM log and exact trade descriptors, without a live decoder."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

__all__ = ["EvmLogDescriptor", "EvmTrade"]

_UINT256_MAX = 2**256 - 1
_ADDRESS = r"^0x[0-9a-fA-F]{40}\z"
_HASH = r"^0x[0-9a-fA-F]{64}\z"


class EvmLogDescriptor(BaseModel):
    """The explicit chain, contract, event and bounded block range to decode."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chain_id: StrictInt = Field(gt=0, le=_UINT256_MAX)
    contract: str = Field(pattern=_ADDRESS)
    event_signature: str = Field(pattern=_HASH)
    decoder_revision: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\z"
    )
    first_block: StrictInt = Field(ge=0, le=_UINT256_MAX)
    last_block: StrictInt = Field(ge=0, le=_UINT256_MAX)

    @model_validator(mode="after")
    def _ordered_blocks(self) -> Self:
        if self.last_block < self.first_block:
            raise ValueError("last_block precedes first_block")
        return self


class EvmTrade(BaseModel):
    """Trade values and immutable event provenance without float conversion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chain_id: StrictInt = Field(gt=0, le=_UINT256_MAX)
    contract: str = Field(pattern=_ADDRESS)
    event_signature: str = Field(pattern=_HASH)
    decoder_revision: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\z"
    )
    transaction_hash: str = Field(pattern=_HASH)
    block_hash: str = Field(pattern=_HASH)
    block_number: StrictInt = Field(ge=0, le=_UINT256_MAX)
    log_index: StrictInt = Field(ge=0, le=_UINT256_MAX)
    asset_in: str = Field(pattern=_ADDRESS)
    asset_out: str = Field(pattern=_ADDRESS)
    amount_in: StrictInt = Field(ge=0, le=_UINT256_MAX)
    amount_out: StrictInt = Field(ge=0, le=_UINT256_MAX)
    scale_in: StrictInt = Field(ge=0, le=255)
    scale_out: StrictInt = Field(ge=0, le=255)
    side: Literal["buy", "sell"]
