"""One provider implementation per feed kind (SDK-OBSERVABILITY-FEEDS-R001).

:class:`agent_connector_sdk.adapters.event_feed.EventFeedSourceAdapter` is one
shared engine; only the feed kind is fixed per binding, so a new feed kind
never needs a new adapter class, only a new name here.
"""

from __future__ import annotations

import functools

from agent_connector_sdk.adapters.event_envelope import FeedKind
from agent_connector_sdk.adapters.event_feed import EventFeedSourceAdapter

__all__ = [
    "ci_cd_source_adapter",
    "rum_source_adapter",
    "security_audit_source_adapter",
]

rum_source_adapter = functools.partial(EventFeedSourceAdapter, feed_kind=FeedKind.RUM)
security_audit_source_adapter = functools.partial(
    EventFeedSourceAdapter, feed_kind=FeedKind.SECURITY_AUDIT
)
ci_cd_source_adapter = functools.partial(
    EventFeedSourceAdapter, feed_kind=FeedKind.CI_CD
)
