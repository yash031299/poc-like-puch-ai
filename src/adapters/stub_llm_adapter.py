"""
StubLLMAdapter — zero-credential Language Model for local development and testing.

Yields a hardcoded response word-by-word to simulate streaming LLM output.
No API key required. Supports fallback responses for error scenarios.

Usage (server.py DEV_MODE):
    llm = StubLLMAdapter(response="I'm your AI assistant. How can I help you today?")
    
For fallback: Use FALLBACK_RESPONSES list for error recovery scenarios.
"""

import random
from typing import AsyncIterator

from src.domain.entities.utterance import Utterance
from src.ports.language_model_port import LanguageModelPort


class StubLLMAdapter(LanguageModelPort):
    """
    Deterministic LLM implementation for local testing.

    Yields the configured response split into words, simulating the token-by-token
    streaming behaviour of a real LLM.  The utterance and context are ignored —
    every call returns the same response.

    Includes fallback responses for error recovery scenarios.
    No external dependencies — safe to use without GEMINI_API_KEY.
    """

    FALLBACK_RESPONSES = [
        "I'm sorry, I didn't catch that. Can you repeat?",
        "I'm having trouble understanding. Please try again.",
        "Let me think about that for a moment.",
        "I'm sorry, could you rephrase that for me?",
        "Sorry, I need you to say that again.",
    ]

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
        self.use_fallback: bool = False

    async def generate(
        self,
        stream_id: str,
        utterance: Utterance,
        context: list[str],
    ) -> AsyncIterator[str]:
        self.call_count += 1
        self.last_utterance_text = utterance.text

        # Use fallback response if flag is set
        response_text = (
            random.choice(self.FALLBACK_RESPONSES)
            if self.use_fallback
            else self._response
        )

        # Yield each word with a trailing space to mimic token streaming
        for word in response_text.split():
            yield word + " "

    async def get_fallback_response(self) -> str:
        """Get a random fallback response for error scenarios."""
        return random.choice(self.FALLBACK_RESPONSES)
