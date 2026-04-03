"""SpeechToTextPort — input port for audio transcription."""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance


class SpeechToTextPort(ABC):
    """
    Driven port for converting audio chunks to text utterances.

    Business Rule: Transcription is streaming — partial results arrive
    before the final utterance. Implementations may use Google STT,
    Deepgram, Whisper, etc.
    """

    @abstractmethod
    async def transcribe(
        self, stream_id: str, chunk: AudioChunk
    ) -> AsyncIterator[Utterance]:
        """
        Transcribe an audio chunk, yielding partial and final utterances.

        Args:
            stream_id: The call stream identifier for routing
            chunk: The audio chunk to transcribe

        Yields:
            Utterance objects (partial then final)
        """
