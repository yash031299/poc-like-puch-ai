"""GeminiLLMAdapter — LanguageModelPort backed by Google Gemini (google-genai SDK)."""

import asyncio
import logging
import os
import random
from typing import AsyncIterator

from google import genai
from google.genai import types

from src.domain.entities.utterance import Utterance
from src.ports.language_model_port import LanguageModelPort

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful, concise voice assistant on a phone call. "
    "Keep responses short (2-3 sentences max) since they will be spoken aloud. "
    "Be warm, natural, and conversational."
)

_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiLLMAdapter(LanguageModelPort):
    """
    Implements LanguageModelPort using Google Gemini streaming API (google-genai SDK).

    Uses gemini-2.5-flash by default and supports bounded retries + model failover
    for transient provider-side capacity errors.
    """

    def __init__(self, api_key: str, model_name: str = _DEFAULT_MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

        fallback_env = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash-lite")
        self._fallback_models = [
            m.strip() for m in fallback_env.split(",") if m.strip() and m.strip() != model_name
        ]
        self._max_attempts = max(1, int(os.getenv("GEMINI_RETRY_MAX_ATTEMPTS", "3")))
        self._base_backoff_ms = max(50, int(os.getenv("GEMINI_RETRY_BASE_MS", "250")))
        self._max_jitter_ms = max(0, int(os.getenv("GEMINI_RETRY_JITTER_MS", "150")))

    def _is_retriable_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and status_code in (429, 500, 502, 503, 504):
            return True

        message = str(exc).upper()
        return any(
            marker in message
            for marker in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "TIMEOUT")
        )

    async def _start_stream(self, model_name: str, contents: list[types.Content], config: types.GenerateContentConfig):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._client.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=config,
            ),
        )

    async def generate(
        self, stream_id: str, utterance: Utterance, context: list[str]
    ) -> AsyncIterator[str]:
        # Build conversation history from prior turns
        contents = []
        for i, turn in enumerate(context):
            role = "user" if i % 2 == 0 else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=turn)]))

        # Add current user utterance
        contents.append(types.Content(role="user", parts=[types.Part(text=utterance.text)]))
        config = types.GenerateContentConfig(system_instruction=_SYSTEM_PROMPT)

        fallback_models = list(getattr(self, "_fallback_models", []))
        max_attempts = max(1, int(getattr(self, "_max_attempts", 3)))
        base_backoff_ms = max(50, int(getattr(self, "_base_backoff_ms", 250)))
        max_jitter_ms = max(0, int(getattr(self, "_max_jitter_ms", 150)))

        candidate_models = [self._model_name, *fallback_models]
        last_error: Exception | None = None

        for model_name in candidate_models:
            for attempt in range(1, max_attempts + 1):
                emitted_any_text = False
                try:
                    stream = await self._start_stream(model_name=model_name, contents=contents, config=config)
                    for chunk in stream:
                        text = chunk.text
                        if text:
                            emitted_any_text = True
                            yield text

                    if emitted_any_text:
                        if attempt > 1 or model_name != self._model_name:
                            logger.info(
                                "Gemini recovered stream=%s model=%s attempt=%d",
                                stream_id,
                                model_name,
                                attempt,
                            )
                        return

                    # No text produced is treated as a transient failure signal.
                    raise RuntimeError(f"Gemini returned empty stream for model={model_name}")
                except Exception as exc:
                    last_error = exc

                    # If response already started, avoid retrying to prevent duplicate partial responses.
                    if emitted_any_text:
                        raise

                    is_retriable = self._is_retriable_error(exc)
                    is_last_attempt = attempt >= max_attempts
                    if not is_retriable or is_last_attempt:
                        logger.warning(
                            "Gemini attempt failed stream=%s model=%s attempt=%d retriable=%s error=%s",
                            stream_id,
                            model_name,
                            attempt,
                            is_retriable,
                            exc,
                        )
                        break

                    backoff_ms = (base_backoff_ms * (2 ** (attempt - 1))) + random.randint(0, max_jitter_ms)
                    logger.warning(
                        "Gemini retriable failure stream=%s model=%s attempt=%d/%d backoff_ms=%d error=%s",
                        stream_id,
                        model_name,
                        attempt,
                        max_attempts,
                        backoff_ms,
                        exc,
                    )
                    await asyncio.sleep(backoff_ms / 1000.0)

            logger.warning("Switching Gemini model stream=%s next_model_available=%s", stream_id, model_name != candidate_models[-1])

        if last_error is not None:
            raise last_error
        raise RuntimeError("Gemini generation failed without a concrete error")
