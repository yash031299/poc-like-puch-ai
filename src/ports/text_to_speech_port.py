"""TextToSpeechPort — driven port for speech synthesis."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

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

    async def synthesize_stream(
        self,
        stream_id: str,
        response_id: str,
        token_buffer: "TokenRingBuffer",  # type: ignore
    ) -> AsyncIterator[SpeechSegment]:
        """
        Synthesize from a stream of LLM tokens instead of complete text.

        This method enables real-time audio synthesis while LLM tokens are still
        being generated. Implementations should:
        - Accumulate tokens from token_buffer
        - Detect phrase/sentence boundaries
        - Synthesize and yield segments as complete phrases become available
        - Return when token_buffer signals complete (EOF)

        Default implementation: Override in subclasses to enable streaming synthesis.
        Raises NotImplementedError if not implemented.

        Args:
            stream_id: The call stream identifier
            response_id: The response ID being synthesized
            token_buffer: TokenRingBuffer yielding LLM tokens

        Yields:
            SpeechSegment objects (last one has is_last=True)

        Raises:
            NotImplementedError: If adapter doesn't support token streaming
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement synthesize_stream()"
        )

