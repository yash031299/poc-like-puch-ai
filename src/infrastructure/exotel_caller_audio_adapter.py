"""ExotelCallerAudioAdapter — CallerAudioPort that sends audio via active WebSocket.

This is a registry-based adapter: WebSocket connections register themselves
on connect and are removed on disconnect. The use case layer calls send_segment
which routes to the correct WebSocket by stream_id.
"""

import asyncio
import base64
import json
import logging
from typing import Any, Dict, Optional

from src.domain.entities.speech_segment import SpeechSegment
from src.ports.caller_audio_port import CallerAudioPort

logger = logging.getLogger(__name__)


class ExotelCallerAudioAdapter(CallerAudioPort):
    """
    Sends synthesized speech back to Exotel via the active WebSocket.

    Exotel expects a JSON media event:
    {
        "event": "media",
        "stream_sid": "<stream_id>",
        "media": { "payload": "<base64-pcm16le>" }
    }
    """

    def __init__(self) -> None:
        self._connections: Dict[str, Any] = {}  # stream_id -> websocket

    def register(self, stream_id: str, websocket: Any) -> None:
        """Register an active WebSocket connection."""
        self._connections[stream_id] = websocket
        logger.debug("Registered WebSocket for stream %s", stream_id)

    def unregister(self, stream_id: str) -> None:
        """Remove a WebSocket connection (call closed)."""
        self._connections.pop(stream_id, None)
        logger.debug("Unregistered WebSocket for stream %s", stream_id)

    async def send_segment(self, stream_id: str, segment: SpeechSegment) -> None:
        """Send a single PCM audio segment to Exotel as a media event."""
        websocket = self._connections.get(stream_id)
        if websocket is None:
            logger.warning("No active WebSocket for stream %s, dropping segment", stream_id)
            return

        payload = base64.b64encode(segment.audio_data).decode("utf-8")
        message = json.dumps({
            "event": "media",
            "stream_sid": stream_id,
            "media": {"payload": payload},
        })

        try:
            await websocket.send_text(message)
        except Exception as exc:
            logger.error("Failed to send audio to stream %s: %s", stream_id, exc)
