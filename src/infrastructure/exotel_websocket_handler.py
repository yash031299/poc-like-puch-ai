"""ExotelWebSocketHandler — routes Exotel AgentStream events to use cases."""

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.services.interrupt_detector import InterruptDetector
from src.domain.value_objects.audio_format import AudioFormat
from src.ports.session_repository_port import SessionRepositoryPort
from src.use_cases.accept_call import AcceptCallUseCase
from src.use_cases.end_call import EndCallUseCase
from src.use_cases.process_audio import ProcessAudioUseCase

logger = logging.getLogger(__name__)


class ExotelWebSocketHandler:
    """
    Infrastructure handler for Exotel AgentStream WebSocket connections.

    Responsibilities:
    - Accept WebSocket connection
    - Parse Exotel JSON events: connected / start / media / mark / stop / dtmf
    - Register the WebSocket with the audio adapter so TTS audio can be sent back
    - Decode base64 audio payloads, preserving Exotel's chunk sequence numbers
    - Delegate to use cases (AcceptCall, ProcessAudio, EndCall)

    This class is intentionally thin: all business logic lives in use cases.
    """

    def __init__(
        self,
        accept_call: AcceptCallUseCase,
        process_audio: ProcessAudioUseCase,
        end_call: EndCallUseCase,
        session_repo: SessionRepositoryPort,
        sample_rate: int = 16000,
        audio_adapter=None,
        reset_session=None,  # ResetSessionUseCase — handles inbound 'clear' from Exotel
        stt=None,  # SpeechToTextPort — held so we can flush its buffer on disconnect
        buffer_manager=None,  # AudioBufferManager — for VAD-based buffering
        interrupt_detector=None,  # InterruptDetector — detect user interruptions
    ) -> None:
        self._accept_call = accept_call
        self._process_audio = process_audio
        self._end_call = end_call
        self._session_repo = session_repo
        self._sample_rate = sample_rate
        self._audio_adapter = audio_adapter
        self._reset_session = reset_session
        self._stt = stt
        self._buffer_manager = buffer_manager
        self._interrupt_detector = interrupt_detector or InterruptDetector()

    async def handle(self, websocket: Any) -> None:
        """
        Main WebSocket handler coroutine.

        Exotel AgentStream event sequence:
          connected → start → media* → (mark*) → stop
        """
        await websocket.accept()

        stream_id: Optional[str] = None
        pending_audio_finalized = False

        try:
            while True:
                try:
                    raw = await websocket.receive_text()
                except Exception:
                    break

                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message, skipping")
                    continue

                event = message.get("event")
                logger.debug("Exotel event: %s stream=%s", event, stream_id)

                if event == "connected":
                    # Exotel sends this immediately on connection before 'start'
                    logger.info("Exotel connection established")

                elif event == "start":
                    stream_id = await self._handle_start(message)
                    if stream_id and self._audio_adapter:
                        self._audio_adapter.register(stream_id, websocket)

                elif event == "media" and stream_id:
                    await self._handle_media(message, stream_id)

                elif event == "mark":
                    # Exotel confirms audio playback reached a named mark point
                    mark_name = message.get("mark", {}).get("name", "")
                    logger.debug("Mark confirmed by Exotel: %s stream=%s", mark_name, stream_id)

                elif event == "stop":
                    if stream_id:
                        # Flush any remaining buffered audio before ending call.
                        # This preserves final caller utterance on stream teardown.
                        await self._finalize_pending_audio(stream_id)
                        pending_audio_finalized = True
                        if self._audio_adapter:
                            self._audio_adapter.unregister(stream_id)
                        await self._handle_stop(stream_id)
                    break

                elif event == "dtmf":
                    digit = message.get("dtmf", {}).get("digit", "")
                    logger.debug("DTMF digit=%s stream=%s", digit, stream_id)

                elif event == "clear":
                    # Exotel sends 'clear' when caller says "start over".
                    # Bot must reset its conversation context AND clear audio buffer.
                    logger.info("Exotel clear received — resetting session context stream=%s", stream_id)
                    if stream_id:
                        # Clear buffer manager state
                        if hasattr(self, '_buffer_manager') and self._buffer_manager:
                            self._buffer_manager.reset(stream_id)
                            logger.info(f"Cleared audio buffer for stream {stream_id}")
                        await self._handle_clear(stream_id)

        except Exception as exc:
            logger.error("WebSocket handler error: %s", exc, exc_info=True)
        finally:
            if stream_id and self._audio_adapter:
                self._audio_adapter.unregister(stream_id)
            # Flush any accumulated audio buffer for this stream and then reset.
            if stream_id and not pending_audio_finalized:
                await self._finalize_pending_audio(stream_id)
            if stream_id and self._buffer_manager:
                self._buffer_manager.reset(stream_id)
            # Flush any accumulated STT audio buffer for this stream
            if stream_id and hasattr(self._stt, "flush"):
                self._stt.flush(stream_id)
            try:
                await websocket.close()
            except Exception:
                pass

    # ── Event handlers ────────────────────────────────────────────────────────

    async def _handle_start(self, message: Dict[str, Any]) -> str:
        """Process 'start' event: extract call metadata and create session."""
        start_data = message.get("start", {})
        # stream_sid is in start.stream_sid AND at top-level
        stream_id = start_data.get("stream_sid") or message.get("stream_sid", "unknown")
        caller = start_data.get("from", "unknown")
        called = start_data.get("to", "unknown")
        custom_params = start_data.get("custom_parameters", {}) or {}

        # Honor sample rate from start.media_format if Exotel provides it
        media_format = start_data.get("media_format", {})
        if media_format.get("sample_rate"):
            try:
                self._sample_rate = int(media_format["sample_rate"])
            except (ValueError, TypeError):
                pass

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

    async def _handle_media(self, message: Dict[str, Any], stream_id: str) -> None:
        """
        Process 'media' event using Exotel's chunk number for ordering.

        Handles network loss gracefully:
        - Partial audio: buffer and process available chunks
        - Invalid payloads: skip and continue
        - Processing errors: log and attempt fallback
        
        Also detects user interruptions using InterruptDetector.
        """
        media = message.get("media", {})
        payload_b64 = media.get("payload", "")

        if not payload_b64:
            return

        try:
            audio_data = base64.b64decode(payload_b64)
        except Exception as e:
            logger.warning(
                "Failed to decode audio payload for stream %s: %s",
                stream_id,
                e,
            )
            return

        if not audio_data:
            logger.debug("Received empty audio payload for stream %s", stream_id)
            return

        # Use Exotel's chunk counter for correct sequence ordering
        try:
            chunk_seq = int(media.get("chunk", 0))
        except (ValueError, TypeError):
            chunk_seq = 0

        audio_format = AudioFormat(
            sample_rate=self._sample_rate,
            encoding="PCM16LE",
            channels=1,
        )
        chunk = AudioChunk(
            sequence_number=chunk_seq,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=audio_data,
        )

        # Detect interrupts if detector is available and session exists
        try:
            if self._interrupt_detector:
                session = await self._session_repo.get(stream_id)
                if session:
                    interrupted = await self._interrupt_detector.detect_interrupt(
                        session, audio_data
                    )
                    if interrupted:
                        logger.info(
                            "User interrupt detected stream=%s during SPEAKING state",
                            stream_id,
                        )
        except Exception as exc:
            logger.debug("Interrupt detection failed stream=%s: %s", stream_id, exc)
            # Continue processing even if interrupt detection fails

        try:
            await self._process_audio.execute(stream_id=stream_id, chunk=chunk)
        except Exception as exc:
            logger.error("ProcessAudio failed stream=%s: %s", stream_id, exc)
            # Continue processing despite error (graceful degradation)
            # Buffer manager will handle partial audio when VAD flushes

    async def _handle_stop(self, stream_id: str) -> None:
        """Process 'stop' event: end the call session."""
        try:
            await self._end_call.execute(stream_id=stream_id)
            logger.info("Call ended: stream=%s", stream_id)
        except ValueError as exc:
            logger.warning("EndCall failed: %s", exc)

    async def _handle_clear(self, stream_id: str) -> None:
        """
        Handle inbound 'clear' from Exotel — reset conversation context.

        Per Exotel docs: Exotel sends clear when caller says 'start over'.
        Wipes utterances, AI responses, and speech segments so the next
        exchange starts fresh. Audio chunks and session state are preserved.
        """
        logger.info("Session context reset requested stream=%s", stream_id)
        if self._reset_session:
            try:
                await self._reset_session.execute(stream_id)
                logger.info("Session context cleared stream=%s", stream_id)
            except Exception as exc:
                logger.error("ResetSession failed stream=%s: %s", stream_id, exc)

    async def _finalize_pending_audio(self, stream_id: str) -> None:
        """Run final VAD flush via use case if supported."""
        if hasattr(self._process_audio, "finalize_stream"):
            try:
                await self._process_audio.finalize_stream(stream_id)
            except Exception as exc:
                logger.error("Finalize pending audio failed stream=%s: %s", stream_id, exc)
