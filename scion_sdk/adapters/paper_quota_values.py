"""Quota lock keys and policy-bound serialization."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scion_sdk.adapters.paper_quota import PaperQuotaPolicy


class QuotaUnavailable(RuntimeError):
    """No source call is allowed because the shared quota is unavailable."""

    def __init__(self, reason: str) -> None:
        if reason not in {"busy", "unavailable", "policy_mismatch"}:
            raise ValueError("invalid quota reason")
        self.reason = reason
        super().__init__(reason)


def _key(policy: PaperQuotaPolicy) -> str:
    payload = json.dumps(
        policy.credential_group,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _encode(owner: str | None, policy: PaperQuotaPolicy) -> bytes:
    return json.dumps(
        {
            "owner": owner,
            "policy_revision": policy.policy_revision,
            "minimum_spacing_ns": policy.minimum_spacing_ns,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _check_free(data: bytes, policy: PaperQuotaPolicy) -> None:
    if data == _encode(None, policy):
        return
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise QuotaUnavailable("unavailable") from None
    if not isinstance(value, dict) or set(value) != {
        "owner",
        "policy_revision",
        "minimum_spacing_ns",
    }:
        raise QuotaUnavailable("unavailable")
    if (
        value["policy_revision"] != policy.policy_revision
        or value["minimum_spacing_ns"] != policy.minimum_spacing_ns
    ):
        raise QuotaUnavailable("policy_mismatch")
    if not isinstance(value["owner"], str) or len(value["owner"]) != 32:
        raise QuotaUnavailable("unavailable")
    raise QuotaUnavailable("busy")
