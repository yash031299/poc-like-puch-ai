"""ResponseStreamerPort — driven port for streaming LLM responses."""

from abc import ABC, abstractmethod
from typing import AsyncIterator


class ResponseStreamerPort(ABC):
    """
    Driven port for streaming AI responses token-by-token from LLM providers.

    Business Rule: Implementations stream tokens asynchronously to minimize
    time-to-first-byte and enable real-time TTS playback. Supports fallback
    to non-streaming mode on error.
    """

    @abstractmethod
    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        """
        Stream tokens from LLM response.

        Args:
            prompt: The prompt text to send to the LLM

        Yields:
            Individual token strings as they are generated
        """
