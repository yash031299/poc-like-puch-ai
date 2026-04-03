"""LanguageModelPort — driven port for AI text generation."""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from src.domain.entities.utterance import Utterance


class LanguageModelPort(ABC):
    """
    Driven port for generating AI responses from caller utterances.

    Business Rule: Responses are streamed token-by-token to minimise
    time-to-first-byte. Implementations may use Gemini, OpenAI, local LLMs, etc.
    """

    @abstractmethod
    async def generate(
        self, stream_id: str, utterance: Utterance, context: list[str]
    ) -> AsyncIterator[str]:
        """
        Generate a streaming AI response for the given utterance.

        Args:
            stream_id: The call stream identifier
            utterance: The caller's final utterance to respond to
            context: Previous turns in the conversation (for memory)

        Yields:
            Text tokens as they are generated
        """
