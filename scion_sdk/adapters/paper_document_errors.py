"""Closed failures for governed paper document transfers."""

from collections.abc import Awaitable

from scion_sdk.adapters.paper_quota import QuotaUnavailable
from scion_sdk.http.client import AirgapViolation
from scion_sdk.http.egress import EgressPolicyError, PinnedEgressViolation


class DocumentRefusal(RuntimeError):
    """A closed document-transfer refusal without source secrets."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _DocumentRateLimit(DocumentRefusal):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("rate_limited")
        self.retry_after = retry_after


async def _translate_download[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except DocumentRefusal:
        raise
    except TimeoutError:
        raise DocumentRefusal("deadline_exceeded") from None
    except (AirgapViolation, EgressPolicyError, PinnedEgressViolation):
        raise DocumentRefusal("egress_denied") from None
    except QuotaUnavailable as error:
        reason = "rate_limited" if error.reason == "busy" else "document_unavailable"
        raise DocumentRefusal(reason) from None
    except Exception:
        raise DocumentRefusal("document_unavailable") from None
