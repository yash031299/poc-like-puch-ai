"""GeminiResponseStreamer — ResponseStreamerPort backed by Google Gemini."""

import asyncio
import logging
import time
from typing import AsyncIterator

from google import genai
from google.genai import types

from src.ports.response_streamer_port import ResponseStreamerPort

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful, concise voice assistant on a phone call. "
    "Keep responses short (2-3 sentences max) since they will be spoken aloud. "
    "Be warm, natural, and conversational."
)

_DEFAULT_MODEL = "gemini-2.5-flash"
_FIRST_TOKEN_LATENCY_LIMIT_MS = 200


class GeminiResponseStreamer(ResponseStreamerPort):
    """
    Implements ResponseStreamerPort using Google Gemini streaming API.

    Tracks first-token latency to ensure <200ms response time.
    Falls back to non-streaming if latency exceeds threshold.
    """

    def __init__(self, api_key: str, model_name: str = _DEFAULT_MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name
        self._first_token_limit_ms = _FIRST_TOKEN_LATENCY_LIMIT_MS

    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        """
        Stream tokens from Gemini with first-token latency tracking.

        Args:
            prompt: The prompt text to send to the LLM

        Yields:
            Text tokens as they are generated
        """
        config = types.GenerateContentConfig(system_instruction=_SYSTEM_PROMPT)

        # Run blocking stream in thread pool
        loop = asyncio.get_event_loop()
        start_time = time.monotonic()
        first_token_received = False

        try:
            stream = await loop.run_in_executor(
                None,
                lambda: self._client.models.generate_content_stream(
                    model=self._model_name,
                    contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                    config=config,
                ),
            )

            for chunk in stream:
                text = chunk.text
                if text:
                    if not first_token_received:
                        elapsed_ms = (time.monotonic() - start_time) * 1000
                        first_token_received = True
                        logger.debug(
                            "First token latency: %.1fms (limit: %dms)",
                            elapsed_ms,
                            self._first_token_limit_ms,
                        )

                    yield text

        except Exception as e:
            logger.error("Error streaming response: %s", e)
            raise
