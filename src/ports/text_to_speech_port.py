"""TextToSpeechPort — driven port for speech synthesis."""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from src.domain.entities.ai_response import AIResponse
from src.domain.entities.speech_segment import SpeechSegment


class TextToSpeechPort(ABC):
    """
    Driven port for converting AI response text to synthesized audio.

    Business Rule: Synthesis is streaming — segments are yielded as soon
    as they are ready so playback can start before synthesis is complete.
    Implementations may use Google TTS, ElevenLabs, Coqui, etc.
    """

    @abstractmethod
    async def synthesize(
        self, stream_id: str, response: AIResponse
    ) -> AsyncIterator[SpeechSegment]:
        """
        Synthesize an AI response into speech audio segments.

        Args:
            stream_id: The call stream identifier
            response: The complete AIResponse whose text to synthesize

        Yields:
            SpeechSegment objects (last one has is_last=True)
        """
