"""PoCSimpleLLMAdapter — deterministic non-streaming conversational adapter for PoC mode."""

import re
from typing import AsyncIterator

from src.domain.entities.utterance import Utterance
from src.ports.language_model_port import LanguageModelPort


class PoCSimpleLLMAdapter(LanguageModelPort):
    """
    Lightweight PoC adapter that avoids external LLM calls entirely.

    It generates a direct, short conversational response as a single chunk
    (non-streaming behavior from provider perspective) while preserving the
    LanguageModelPort streaming contract.
    """

    def __init__(
        self,
        default_response: str = (
            "Hello! Thanks for calling. I can hear you clearly and this PoC mode is "
            "working. Please tell me how I can help you today."
        ),
        greeting_response: str = (
            "Hi! Yes, I can hear you. This is the PoC conversation mode and I am ready "
            "to continue."
        ),
    ) -> None:
        self._default_response = default_response.strip()
        self._greeting_response = greeting_response.strip()

    async def generate(
        self,
        stream_id: str,
        utterance: Utterance,
        context: list[str],
    ) -> AsyncIterator[str]:
        del stream_id, context  # unused in deterministic PoC mode

        text = (utterance.text or "").strip().lower()
        words = set(re.findall(r"[a-zA-Z']+", text))
        if {"hi", "hello", "hey"} & words:
            yield self._greeting_response
            return

        yield self._default_response
