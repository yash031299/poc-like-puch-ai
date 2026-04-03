"""
StubLLMAdapter — zero-credential Language Model for local development and testing.

Yields a hardcoded response word-by-word to simulate streaming LLM output.
No API key required.

Usage (server.py DEV_MODE):
    llm = StubLLMAdapter(response="I'm your AI assistant. How can I help you today?")
"""

from typing import AsyncIterator

from src.domain.entities.utterance import Utterance
from src.ports.language_model_port import LanguageModelPort


class StubLLMAdapter(LanguageModelPort):
    """
    Deterministic LLM implementation for local testing.

    Yields the configured response split into words, simulating the token-by-token
    streaming behaviour of a real LLM.  The utterance and context are ignored —
    every call returns the same response.

    No external dependencies — safe to use without GEMINI_API_KEY.
    """

    def __init__(
        self,
        response: str = (
            "Hello! I am your AI voice assistant and I am working correctly. "
            "This is a local stub response. How can I help you today?"
        ),
    ) -> None:
        self._response = response
        # Track calls for test assertions
        self.call_count: int = 0
        self.last_utterance_text: str = ""

    async def generate(
        self,
        stream_id: str,
        utterance: Utterance,
        context: list[str],
    ) -> AsyncIterator[str]:
        self.call_count += 1
        self.last_utterance_text = utterance.text

        # Yield each word with a trailing space to mimic token streaming
        for word in self._response.split():
            yield word + " "
