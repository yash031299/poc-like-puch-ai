"""ExotelWebSocketHandler — routes Exotel AgentStream events to use cases."""

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.value_objects.audio_format import AudioFormat
from src.use_cases.accept_call import AcceptCallUseCase
from src.use_cases.end_call import EndCallUseCase
from src.use_cases.process_audio import ProcessAudioUseCase

logger = logging.getLogger(__name__)

# Default audio format for Exotel (overridden by start message if provided)
_DEFAULT_AUDIO_FORMAT = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

# Sample rate map from Exotel query params
_SAMPLE_RATE_MAP = {8000: 8000, 16000: 16000, 24000: 24000}


class ExotelWebSocketHandler:
    """
    Infrastructure handler for Exotel AgentStream WebSocket connections.

    Responsibilities:
    - Accept WebSocket connection
    - Parse Exotel JSON events (start / media / stop / dtmf)
    - Decode base64 audio payloads
    - Delegate to use cases (AcceptCall, ProcessAudio, EndCall)

    This class is intentionally thin: all business logic lives in use cases.
    """

    def __init__(
        self,
        accept_call: AcceptCallUseCase,
        process_audio: ProcessAudioUseCase,
        end_call: EndCallUseCase,
        sample_rate: int = 16000,
    ) -> None:
        self._accept_call = accept_call
        self._process_audio = process_audio
        self._end_call = end_call
        self._sample_rate = sample_rate

    async def handle(self, websocket: Any) -> None:
        """
        Main WebSocket handler coroutine.

        Accepts the connection then reads messages in a loop until
        the connection closes or a 'stop' event is received.
        """
        await websocket.accept()

        stream_id: Optional[str] = None
        seq: int = 0

        try:
            while True:
                try:
                    raw = await websocket.receive_text()
                except Exception:
                    # Connection closed by remote
                    break

                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message, skipping")
                    continue

                event = message.get("event")
                logger.debug("Exotel event: %s stream=%s", event, stream_id)

                if event == "start":
                    stream_id = await self._handle_start(message)

                elif event == "media" and stream_id:
                    seq += 1
                    await self._handle_media(message, stream_id, seq)

                elif event == "stop":
                    if stream_id:
                        await self._handle_stop(stream_id)
                    break

                elif event == "dtmf":
                    logger.debug("DTMF received (not handled yet)")

        except Exception as exc:
            logger.error("WebSocket handler error: %s", exc, exc_info=True)
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    # ── Event handlers ────────────────────────────────────────────────────────

    async def _handle_start(self, message: Dict[str, Any]) -> str:
        """Process 'start' event: create session via use case."""
        start_data = message.get("start", {})
        stream_id = start_data.get("stream_sid", message.get("stream_sid", "unknown"))
        caller = start_data.get("from", "unknown")
        called = start_data.get("to", "unknown")
        custom_params = start_data.get("custom_parameters", {}) or {}

        # Determine audio format (Exotel provides sample rate in path params)
        audio_format = AudioFormat(
            sample_rate=self._sample_rate,
            encoding="PCM16LE",
            channels=1,
        )

        try:
            await self._accept_call.execute(
                stream_id=stream_id,
                caller_number=caller,
                called_number=called,
                audio_format=audio_format,
                custom_parameters={str(k): str(v) for k, v in custom_params.items()} or None,
            )
            logger.info("Call accepted: stream=%s caller=%s", stream_id, caller)
        except ValueError as exc:
            logger.warning("Accept call failed: %s", exc)

        return stream_id

    async def _handle_media(
        self, message: Dict[str, Any], stream_id: str, seq: int
    ) -> None:
        """Process 'media' event: decode audio and pass to ProcessAudio use case."""
        media = message.get("media", {})
        payload_b64 = media.get("payload", "")

        if not payload_b64:
            return

        try:
            audio_data = base64.b64decode(payload_b64)
        except Exception:
            logger.warning("Failed to decode audio payload for stream %s", stream_id)
            return

        if not audio_data:
            return

        audio_format = AudioFormat(
            sample_rate=self._sample_rate,
            encoding="PCM16LE",
            channels=1,
        )
        chunk = AudioChunk(
            sequence_number=seq,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=audio_data,
        )

        try:
            await self._process_audio.execute(stream_id=stream_id, chunk=chunk)
        except Exception as exc:
            logger.error("ProcessAudio failed stream=%s: %s", stream_id, exc)

    async def _handle_stop(self, stream_id: str) -> None:
        """Process 'stop' event: end the call session."""
        try:
            await self._end_call.execute(stream_id=stream_id)
            logger.info("Call ended: stream=%s", stream_id)
        except ValueError as exc:
            logger.warning("EndCall failed: %s", exc)
