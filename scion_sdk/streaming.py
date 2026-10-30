"""Topic-based message streaming over WebSocket.

:class:`StreamBus` fans published :class:`StreamMessage` objects out to
subscribers by topic; :class:`WebSocketStreamAdapter` feeds a bus from a
WebSocket source. The ``stream`` extra supplies the WebSocket client.
"""

from __future__ import annotations

from scion_sdk._stream_bus import StreamBus
from scion_sdk._stream_types import CallbackSubscriber, StreamMessage, StreamSubscriber
from scion_sdk._stream_websocket import WebSocketStreamAdapter

__all__ = [
    "CallbackSubscriber",
    "StreamBus",
    "StreamMessage",
    "StreamSubscriber",
    "WebSocketStreamAdapter",
]
