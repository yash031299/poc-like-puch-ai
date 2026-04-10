"""ExotelCallerAudioAdapter — CallerAudioPort that sends audio via active WebSocket.

This is a registry-based adapter: WebSocket connections register themselves
on connect and are removed on disconnect. The use case layer calls send_segment
which routes to the correct WebSocket by stream_id.

Implements bidirectional streaming protocol:
- Outbound events include sequence_number (monotonically increasing per stream)
- Media events include timestamp (milliseconds from stream start)
- All chunks validated as multiples of 320 bytes per Exotel spec
"""

import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, Optional

from src.domain.entities.speech_segment import SpeechSegment
from src.ports.caller_audio_port import CallerAudioPort

logger = logging.getLogger(__name__)


class ExotelCallerAudioAdapter(CallerAudioPort):
    """
    Sends synthesized speech back to Exotel via the active WebSocket.

    Implements bidirectional streaming per Exotel AgentStream protocol:
    - sequence_number: monotonically increasing per stream, starting at 1
    - timestamp: milliseconds from stream start (for media events)
    - chunk validation: all audio payloads must be multiples of 320 bytes

    Exotel expects JSON events like:
    {
        "event": "media",
        "sequence_number": 1,
        "stream_sid": "<stream_id>",
        "media": { "payload": "<base64-pcm16le>", "timestamp": "1000" }
    }
    """

    def __init__(self) -> None:
        self._connections: Dict[str, Any] = {}  # stream_id -> websocket
        self._sent_segment_counts: Dict[str, int] = {}
        self._sequence_numbers: Dict[str, int] = {}  # stream_id -> next sequence number
        self._stream_start_times: Dict[str, float] = {}  # stream_id -> time.monotonic()

    def register(self, stream_id: str, websocket: Any) -> None:
        """Register an active WebSocket connection."""
        self._connections[stream_id] = websocket
        self._sent_segment_counts.setdefault(stream_id, 0)
        self._sequence_numbers[stream_id] = 1  # Start sequence at 1 per Exotel spec
        self._stream_start_times[stream_id] = time.monotonic()  # Track start time for timestamp
        logger.debug("Registered WebSocket for stream %s", stream_id)

    def unregister(self, stream_id: str) -> None:
        """Remove a WebSocket connection (call closed)."""
        self._connections.pop(stream_id, None)
        self._sent_segment_counts.pop(stream_id, None)
        self._sequence_numbers.pop(stream_id, None)
        self._stream_start_times.pop(stream_id, None)
        logger.debug("Unregistered WebSocket for stream %s", stream_id)

    async def send_segment(self, stream_id: str, segment: SpeechSegment) -> None:
        """
        Send a single PCM audio segment to Exotel as a media event.
        
        Validates chunk size and includes protocol-required fields:
        - sequence_number: monotonically increasing per stream
        - timestamp: milliseconds from stream start
        """
        websocket = self._connections.get(stream_id)
        if websocket is None:
            logger.warning("No active WebSocket for stream %s, dropping segment", stream_id)
            return

        # Validate chunk size per Exotel spec: must be multiple of 320 bytes
        chunk_size = len(segment.audio_data)
        assert chunk_size % 320 == 0, (
            f"Audio chunk for stream {stream_id} is {chunk_size} bytes; "
            f"must be multiple of 320 bytes per Exotel spec"
        )

        payload = base64.b64encode(segment.audio_data).decode("utf-8")
        
        # Calculate timestamp in milliseconds from stream start
        elapsed_seconds = time.monotonic() - self._stream_start_times[stream_id]
        timestamp_ms = int(elapsed_seconds * 1000)
        
        # Get and increment sequence number
        seq_num = self._sequence_numbers[stream_id]
        self._sequence_numbers[stream_id] += 1
        
        message = json.dumps({
            "event": "media",
            "sequence_number": seq_num,
            "stream_sid": stream_id,
            "media": {
                "payload": payload,
                "timestamp": str(timestamp_ms),
            },
        })

        try:
            logger.debug(
                "Sending media to stream %s: seq=%d bytes=%d timestamp=%dms",
                stream_id, seq_num, chunk_size, timestamp_ms
            )
            await websocket.send_text(message)
            self._sent_segment_counts[stream_id] = self._sent_segment_counts.get(stream_id, 0) + 1
        except Exception as exc:
            logger.error("Failed to send audio to stream %s: %s", stream_id, exc)

    def get_sent_segment_count(self, stream_id: str) -> int:
        """Return number of media segments sent for this stream."""
        return self._sent_segment_counts.get(stream_id, 0)

    async def send_mark(self, stream_id: str, label: str) -> None:
        """
        Send a 'mark' event to Exotel.

        Exotel will echo this mark back when playback reaches this point,
        allowing us to track which audio segments have been played.
        """
        websocket = self._connections.get(stream_id)
        if websocket is None:
            return

        seq_num = self._sequence_numbers[stream_id]
        self._sequence_numbers[stream_id] += 1

        message = json.dumps({
            "event": "mark",
            "sequence_number": seq_num,
            "stream_sid": stream_id,
            "mark": {"name": label},
        })
        try:
            logger.debug("Sending mark to stream %s: seq=%d name=%s", stream_id, seq_num, label)
            await websocket.send_text(message)
        except Exception as exc:
            logger.error("Failed to send mark to stream %s: %s", stream_id, exc)

    async def send_clear(self, stream_id: str) -> None:
        """
        Send a 'clear' event to Exotel to flush buffered audio.

        Use this for barge-in: when caller speaks, clear the AI's pending
        audio so the response doesn't continue playing over the caller.
        """
        websocket = self._connections.get(stream_id)
        if websocket is None:
            return

        seq_num = self._sequence_numbers[stream_id]
        self._sequence_numbers[stream_id] += 1

        message = json.dumps({
            "event": "clear",
            "sequence_number": seq_num,
            "stream_sid": stream_id,
        })
        try:
            logger.debug("Sending clear to stream %s: seq=%d", stream_id, seq_num)
            await websocket.send_text(message)
        except Exception as exc:
            logger.error("Failed to send clear to stream %s: %s", stream_id, exc)
