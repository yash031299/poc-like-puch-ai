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
import array
import base64
import json
import logging
import sys
import time
from typing import Any, Dict, Optional

from src.domain.entities.speech_segment import SpeechSegment
from src.ports.caller_audio_port import CallerAudioPort

logger = logging.getLogger(__name__)


def _resample_pcm16_mono(
    audio_data: bytes, source_sample_rate: int, target_sample_rate: int
) -> bytes:
    """
    Resample PCM16LE mono audio without optional stdlib modules.

    Uses linear interpolation so runtime remains compatible with Python versions
    where `audioop` is unavailable.
    """
    if source_sample_rate == target_sample_rate or not audio_data:
        return audio_data

    if len(audio_data) % 2 != 0:
        raise ValueError("PCM16 audio byte length must be even")

    src = array.array("h")
    src.frombytes(audio_data)
    if sys.byteorder != "little":
        src.byteswap()

    src_len = len(src)
    if src_len == 0:
        return b""

    dst_len = max(1, int(round(src_len * target_sample_rate / source_sample_rate)))
    dst = array.array("h", [0] * dst_len)

    step = source_sample_rate / target_sample_rate
    for i in range(dst_len):
        pos = i * step
        left = int(pos)
        frac = pos - left
        if left >= src_len - 1:
            sample = src[-1]
        else:
            s1 = src[left]
            s2 = src[left + 1]
            sample = int(s1 + (s2 - s1) * frac)
        dst[i] = max(-32768, min(32767, sample))

    if sys.byteorder != "little":
        dst.byteswap()
    return dst.tobytes()


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
        self._media_chunk_numbers: Dict[str, int] = {}  # stream_id -> next media chunk number
        self._media_timestamps_ms: Dict[str, int] = {}  # stream_id -> next media timestamp offset
        self._stream_start_times: Dict[str, float] = {}  # stream_id -> time.monotonic()
        self._stream_sample_rates: Dict[str, int] = {}  # stream_id -> negotiated Exotel sample rate
        self._pacing_enabled: Dict[str, bool] = {}  # stream_id -> pace outbound media in real time

    def register(self, stream_id: str, websocket: Any, sample_rate: Optional[int] = None) -> None:
        """Register an active WebSocket connection."""
        self._connections[stream_id] = websocket
        self._sent_segment_counts.setdefault(stream_id, 0)
        self._sequence_numbers[stream_id] = 1  # Start sequence at 1 per Exotel spec
        self._media_chunk_numbers[stream_id] = 1  # Start media chunk numbering at 1
        self._media_timestamps_ms[stream_id] = 0  # Start media timestamps at 0ms
        self._stream_start_times[stream_id] = time.monotonic()  # Track start time for timestamp
        self._pacing_enabled[stream_id] = sample_rate is not None
        if sample_rate:
            self._stream_sample_rates[stream_id] = max(1, int(sample_rate))
        logger.debug("Registered WebSocket for stream %s", stream_id)

    def unregister(self, stream_id: str) -> None:
        """Remove a WebSocket connection (call closed)."""
        self._connections.pop(stream_id, None)
        self._sent_segment_counts.pop(stream_id, None)
        self._sequence_numbers.pop(stream_id, None)
        self._media_chunk_numbers.pop(stream_id, None)
        self._media_timestamps_ms.pop(stream_id, None)
        self._stream_start_times.pop(stream_id, None)
        self._stream_sample_rates.pop(stream_id, None)
        self._pacing_enabled.pop(stream_id, None)
        logger.debug("Unregistered WebSocket for stream %s", stream_id)

    def _prepare_outbound_audio(
        self, stream_id: str, segment: SpeechSegment
    ) -> tuple[bytes, int, int]:
        """
        Normalize outbound audio for Exotel.

        - Resample to negotiated stream sample rate when needed.
        - Pad to a multiple of 320 bytes per Exotel media constraints.
        """
        audio_data = segment.audio_data
        source_sample_rate = max(1, int(segment.audio_format.sample_rate))
        channels = max(1, int(segment.audio_format.channels))
        target_sample_rate = max(
            1, int(self._stream_sample_rates.get(stream_id, source_sample_rate))
        )

        if target_sample_rate != source_sample_rate:
            # Exotel media is mono PCM16LE. Keep transformation explicit/safe.
            if channels != 1:
                raise ValueError(
                    f"Unsupported channel count for resampling stream {stream_id}: {channels}"
                )
            audio_data = _resample_pcm16_mono(
                audio_data,
                source_sample_rate,
                target_sample_rate,
            )

        remainder = len(audio_data) % 320
        if remainder:
            audio_data += b"\x00" * (320 - remainder)

        return audio_data, source_sample_rate, target_sample_rate

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

        source_chunk_size = len(segment.audio_data)
        assert source_chunk_size % 320 == 0, (
            f"Audio chunk for stream {stream_id} is {source_chunk_size} bytes; "
            f"must be multiple of 320 bytes per Exotel spec"
        )

        audio_data, source_sample_rate, target_sample_rate = self._prepare_outbound_audio(
            stream_id, segment
        )

        # Validate chunk size per Exotel spec: must be multiple of 320 bytes
        chunk_size = len(audio_data)
        assert chunk_size % 320 == 0, (
            f"Normalized audio chunk for stream {stream_id} is {chunk_size} bytes; "
            "must be multiple of 320 bytes per Exotel spec"
        )

        payload = base64.b64encode(audio_data).decode("utf-8")

        # Exotel expects media.timestamp in milliseconds from stream start.
        # Keep timestamps monotonic and advance by audio duration per segment.
        channels = max(1, int(segment.audio_format.channels))
        bytes_per_second = target_sample_rate * channels * 2  # PCM16LE = 2 bytes/sample
        duration_ms = max(1, int((chunk_size * 1000) / bytes_per_second))
        elapsed_ms = int((time.monotonic() - self._stream_start_times[stream_id]) * 1000)
        timestamp_ms = max(self._media_timestamps_ms[stream_id], elapsed_ms)
        self._media_timestamps_ms[stream_id] = timestamp_ms + duration_ms
        
        # Get and increment sequence number
        seq_num = self._sequence_numbers[stream_id]
        self._sequence_numbers[stream_id] += 1
        
        # Media event 'chunk' is required by Exotel media schema.
        media_chunk = self._media_chunk_numbers[stream_id]
        self._media_chunk_numbers[stream_id] += 1

        message = json.dumps({
            "event": "media",
            "sequence_number": seq_num,
            "sequenceNumber": str(seq_num),
            "stream_sid": stream_id,
            "streamSid": stream_id,
            "media": {
                "chunk": media_chunk,
                "payload": payload,
                "timestamp": str(timestamp_ms),
                "sequenceNumber": str(seq_num),
            },
        })

        try:
            if self._pacing_enabled.get(stream_id, False):
                target_send_time = self._stream_start_times[stream_id] + (
                    timestamp_ms / 1000.0
                )
                sleep_seconds = target_send_time - time.monotonic()
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
            logger.debug(
                "Sending media to stream %s: seq=%d chunk=%s bytes=%d "
                "timestamp=%dms duration=%dms sample_rate=%d->%d",
                stream_id,
                seq_num,
                media_chunk,
                chunk_size,
                timestamp_ms,
                duration_ms,
                source_sample_rate,
                target_sample_rate,
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
            "sequenceNumber": str(seq_num),
            "stream_sid": stream_id,
            "streamSid": stream_id,
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
            "sequenceNumber": str(seq_num),
            "stream_sid": stream_id,
            "streamSid": stream_id,
        })
        try:
            logger.debug("Sending clear to stream %s: seq=%d", stream_id, seq_num)
            await websocket.send_text(message)
        except Exception as exc:
            logger.error("Failed to send clear to stream %s: %s", stream_id, exc)
