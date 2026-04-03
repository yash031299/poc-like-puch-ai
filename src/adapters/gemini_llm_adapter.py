"""GeminiLLMAdapter — LanguageModelPort backed by Google Gemini."""

from typing import AsyncIterator
import asyncio

import google.generativeai as genai

from src.domain.entities.utterance import Utterance
from src.ports.language_model_port import LanguageModelPort


_SYSTEM_PROMPT = (
    "You are a helpful, concise voice assistant on a phone call. "
    "Keep responses short (2-3 sentences max) since they will be spoken aloud. "
    "Be warm, natural, and conversational."
)


class GeminiLLMAdapter(LanguageModelPort):
    """
    Implements LanguageModelPort using Google Gemini streaming API.

    Token streaming is emulated by iterating the response chunks.
    For PoC: uses gemini-1.5-flash (free tier, low latency).
    """

    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash") -> None:
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=_SYSTEM_PROMPT,
        )

    async def generate(
        self, stream_id: str, utterance: Utterance, context: list[str]
    ) -> AsyncIterator[str]:
        # Build conversation history from context
        history = []
        for i, turn in enumerate(context):
            role = "user" if i % 2 == 0 else "model"
            history.append({"role": role, "parts": [turn]})

        # Run blocking SDK call in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._model.generate_content(
                history + [{"role": "user", "parts": [utterance.text]}],
                stream=True,
            ),
        )

        for chunk in response:
            if chunk.text:
                yield chunk.text
