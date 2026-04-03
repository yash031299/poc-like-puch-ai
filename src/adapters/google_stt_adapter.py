"""GoogleSTTAdapter — SpeechToTextPort backed by Google Cloud Speech-to-Text."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, Optional

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance
from src.ports.speech_to_text_port import SpeechToTextPort

logger = logging.getLogger(__name__)

# Google STT synchronous recognize needs a reasonable amount of audio to detect
# speech.  Sending individual 20 ms chunks (320 bytes at 8 kHz) always returns
# empty results because the audio is too short to contain recognisable phonemes.
#
# MIN_BUFFER_BYTES sets how much audio to accumulate before we call STT.
# Default: 16 000 bytes = 1 second at 8 kHz PCM16LE mono (8000 * 2 * 1.0).
# For 16 kHz: 32 000 bytes.  The value is scaled by sample_rate so you only
# ever need to pass the sample rate — the minimum is always ~1 second.
_BYTES_PER_SAMPLE = 2  # PCM16LE = 2 bytes per mono sample
_MIN_BUFFER_SECONDS = 1.0  # accumulate at least this many seconds before STT


class GoogleSTTAdapter(SpeechToTextPort):
    """
    Implements SpeechToTextPort using Google Cloud Speech-to-Text v1.

    Client is lazily initialized on first use so the server starts even
    when GOOGLE_APPLICATION_CREDENTIALS is not set (fails at first real call).

    Audio buffering
    ───────────────
    Each incoming chunk is only ~20 ms of audio (320 bytes at 8 kHz).  Google
    STT synchronous `recognize` needs ≥1 second of speech to return a useful
    transcript.  This adapter maintains a per-stream byte buffer and only calls
    STT when the accumulated audio reaches `min_buffer_bytes` (default 1 s).

    For PoC: uses synchronous recognize per buffer window (streaming recognize
    requires a persistent gRPC stream — that's a Phase 4 optimization).
    """

    def __init__(
        self,
        language_code: str = "en-US",
        sample_rate: int = 8000,
        min_buffer_seconds: float = _MIN_BUFFER_SECONDS,
    ) -> None:
        self._language_code = language_code
        self._sample_rate = sample_rate
        self._min_buffer_bytes: int = int(
            min_buffer_seconds * sample_rate * _BYTES_PER_SAMPLE
        )
        self._client = None  # lazy init
        # Per-stream audio accumulation buffers
        self._buffers: Dict[str, bytearray] = {}

    def _get_client(self):
        if self._client is None:
            from google.cloud import speech
            self._client = speech.SpeechClient()
        return self._client

    def flush(self, stream_id: str) -> None:
        """Discard buffered audio for a stream (call on session teardown)."""
        self._buffers.pop(stream_id, None)

    async def transcribe(
        self, stream_id: str, chunk: AudioChunk
    ) -> AsyncIterator[Utterance]:
        # Accumulate audio into the per-stream buffer
        buf = self._buffers.setdefault(stream_id, bytearray())
        buf.extend(chunk.audio_data)

        if len(buf) < self._min_buffer_bytes:
            # Not enough audio yet — yield nothing and wait for more chunks
            return

        # Snapshot and clear the buffer *before* the blocking STT call so that
        # new chunks that arrive during the API round-trip go into a fresh buffer.
        audio_to_send = bytes(buf)
        self._buffers[stream_id] = bytearray()

        logger.debug(
            "STT: sending %d bytes (%.2f s) for stream %s",
            len(audio_to_send),
            len(audio_to_send) / (chunk.audio_format.sample_rate * _BYTES_PER_SAMPLE),
            stream_id,
        )

        # Run blocking SDK call in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._recognize, audio_to_send, chunk.audio_format.sample_rate
        )

        for transcript, confidence in result:
            yield Utterance(
                text=transcript,
                confidence=confidence,
                is_final=True,
                timestamp=datetime.now(timezone.utc),
            )

    def _recognize(self, audio_data: bytes, sample_rate: int) -> list[tuple[str, float]]:
        """Synchronous Google STT call (runs in thread pool)."""
        from google.cloud import speech
        client = self._get_client()
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code=self._language_code,
        )
        audio = speech.RecognitionAudio(content=audio_data)

        response = client.recognize(config=config, audio=audio)

        results = []
        for result in response.results:
            alt = result.alternatives[0]
            confidence = max(0.0, min(1.0, alt.confidence)) if alt.confidence else 0.8
            if alt.transcript.strip():
                results.append((alt.transcript.strip(), confidence))
        return results

