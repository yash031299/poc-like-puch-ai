"""GoogleSTTAdapter — SpeechToTextPort backed by Google Cloud Speech-to-Text."""

import asyncio
import base64
from datetime import datetime, timezone
from typing import AsyncIterator

from google.cloud import speech

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance
from src.ports.speech_to_text_port import SpeechToTextPort


class GoogleSTTAdapter(SpeechToTextPort):
    """
    Implements SpeechToTextPort using Google Cloud Speech-to-Text v1.

    For PoC: uses synchronous recognize per chunk (streaming recognize
    requires a persistent gRPC stream — that's a Phase 4 optimization).
    Yields a single final utterance per chunk.
    """

    def __init__(self, language_code: str = "en-US") -> None:
        self._client = speech.SpeechClient()
        self._language_code = language_code

    async def transcribe(
        self, stream_id: str, chunk: AudioChunk
    ) -> AsyncIterator[Utterance]:
        # Run blocking SDK call in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._recognize, chunk)

        for transcript, confidence in result:
            yield Utterance(
                text=transcript,
                confidence=confidence,
                is_final=True,
                timestamp=datetime.now(timezone.utc),
            )

    def _recognize(self, chunk: AudioChunk) -> list[tuple[str, float]]:
        """Synchronous Google STT call (runs in thread pool)."""
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=chunk.audio_format.sample_rate,
            language_code=self._language_code,
        )
        audio = speech.RecognitionAudio(content=chunk.audio_data)

        response = self._client.recognize(config=config, audio=audio)

        results = []
        for result in response.results:
            alt = result.alternatives[0]
            # Clamp confidence to [0, 1]; Google returns 0.0 if unavailable
            confidence = max(0.0, min(1.0, alt.confidence)) if alt.confidence else 0.8
            if alt.transcript.strip():
                results.append((alt.transcript.strip(), confidence))
        return results
