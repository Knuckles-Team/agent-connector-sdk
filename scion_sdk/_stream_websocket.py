"""WebSocket feed into a :class:`StreamBus`."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from scion_sdk._stream_bus import StreamBus
from scion_sdk._stream_types import StreamMessage

logger = logging.getLogger(__name__)


class WebSocketStreamAdapter:
    """Feeds a :class:`StreamBus` from a WebSocket source.

    ``connect`` opens the connection (default: ``websockets.connect`` from the
    ``stream`` extra). Each JSON text frame becomes a published
    :class:`StreamMessage`; a frame that is not JSON is skipped.
    """

    def __init__(
        self,
        bus: StreamBus,
        url: str = "",
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        self.bus = bus
        self.url = url
        self._connect = connect
        self._connected = False
        self._connection: Any = None

    async def connect(self) -> bool:
        """Open the connection; ``False`` when the client or the peer is unavailable."""
        opener = self._connect
        if opener is None:
            try:
                import websockets
            except ImportError:
                logger.error("WebSocket streaming needs scion-sdk[stream]")
                return False
            opener = websockets.connect
        try:
            self._connection = await opener(self.url)
        except Exception as exc:
            logger.error("WebSocket connection failed (%s)", type(exc).__name__)
            return False
        self._connected = True
        return True

    async def disconnect(self) -> None:
        """Close the connection."""
        if self._connection is not None:
            await self._connection.close()
        self._connected = False

    async def listen(self, topic_prefix: str = "") -> None:
        """Publish every incoming JSON frame, under ``topic_prefix`` when given."""
        if self._connection is None:
            return
        try:
            async for raw_message in self._connection:
                await self._publish_frame(raw_message, topic_prefix)
        except Exception as exc:
            logger.error("WebSocket listen ended (%s)", type(exc).__name__)
            self._connected = False

    async def _publish_frame(self, raw_message: str, topic_prefix: str) -> None:
        try:
            msg = StreamMessage.from_json(raw_message)
        except json.JSONDecodeError:
            logger.warning("skipped a WebSocket frame that is not JSON")
            return
        if topic_prefix:
            msg.topic = ".".join((topic_prefix, msg.topic))
        await self.bus.publish(msg)

    @property
    def is_connected(self) -> bool:
        """Whether the connection is open."""
        return self._connected
