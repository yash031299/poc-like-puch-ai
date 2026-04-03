"""
StubSTTAdapter — zero-credential Speech-to-Text for local development and testing.

Returns a hardcoded transcript after receiving N audio chunks (default 3).
The intent is to exercise the full STT → LLM → TTS pipeline without any
Google Cloud credentials.

Usage (server.py DEV_MODE):
    stt = StubSTTAdapter(transcript="Hello, can you hear me?", trigger_every=3)
"""

from datetime import datetime, timezone
from typing import AsyncIterator

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance
from src.ports.speech_to_text_port import SpeechToTextPort


class StubSTTAdapter(SpeechToTextPort):
    """
    Deterministic STT implementation for local testing.

    Emits one final Utterance with a fixed transcript every `trigger_every`
    chunks received for the same stream_id.  All other chunks are silently
    consumed (simulating the STT engine accumulating audio).

    No external dependencies — safe to use without GOOGLE_APPLICATION_CREDENTIALS.
    """

    def __init__(
        self,
        transcript: str = "Hello, can you hear me? This is a local test.",
        trigger_every: int = 3,
        confidence: float = 0.99,
    ) -> None:
        self._transcript = transcript
        self._trigger_every = trigger_every
        self._confidence = confidence
        # Per-stream chunk counter: stream_id -> count
        self._counters: dict[str, int] = {}

    async def transcribe(
        self, stream_id: str, chunk: AudioChunk
    ) -> AsyncIterator[Utterance]:
        count = self._counters.get(stream_id, 0) + 1
        self._counters[stream_id] = count

        if count % self._trigger_every == 0:
            yield Utterance(
                text=self._transcript,
                confidence=self._confidence,
                is_final=True,
                timestamp=datetime.now(timezone.utc),
            )
        # On other chunks: yield nothing (simulates STT still listening)
        return
