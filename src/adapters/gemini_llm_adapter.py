"""GeminiLLMAdapter — LanguageModelPort backed by Google Gemini (google-genai SDK)."""

from typing import AsyncIterator
import asyncio

from google import genai
from google.genai import types

from src.domain.entities.utterance import Utterance
from src.ports.language_model_port import LanguageModelPort


_SYSTEM_PROMPT = (
    "You are a helpful, concise voice assistant on a phone call. "
    "Keep responses short (2-3 sentences max) since they will be spoken aloud. "
    "Be warm, natural, and conversational."
)

_DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiLLMAdapter(LanguageModelPort):
    """
    Implements LanguageModelPort using Google Gemini streaming API (google-genai SDK).

    Uses gemini-2.0-flash for low latency on the free tier.
    Streaming via generate_content_stream runs in a thread pool to avoid
    blocking the async event loop.
    """

    def __init__(self, api_key: str, model_name: str = _DEFAULT_MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

    async def generate(
        self, stream_id: str, utterance: Utterance, context: list[str]
    ) -> AsyncIterator[str]:
        # Build conversation history from prior turns
        contents = []
        for i, turn in enumerate(context):
            role = "user" if i % 2 == 0 else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=turn)]))

        # Add current user utterance
        contents.append(
            types.Content(role="user", parts=[types.Part(text=utterance.text)])
        )

        config = types.GenerateContentConfig(system_instruction=_SYSTEM_PROMPT)

        # Run blocking stream in thread pool so we don't block the event loop
        loop = asyncio.get_event_loop()
        stream = await loop.run_in_executor(
            None,
            lambda: self._client.models.generate_content_stream(
                model=self._model_name,
                contents=contents,
                config=config,
            ),
        )

        for chunk in stream:
            text = chunk.text
            if text:
                yield text

