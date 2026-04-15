"""PoCGreetingThenLLMAdapter — first greeting, then non-streaming LLM replies."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from src.domain.entities.utterance import Utterance
from src.ports.language_model_port import LanguageModelPort

try:
    from google import genai
    from google.genai import types

    _GENAI_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - validated by runtime checks
    genai = None  # type: ignore
    types = None  # type: ignore
    _GENAI_AVAILABLE = False


logger = logging.getLogger(__name__)


class PoCGreetingThenLLMAdapter(LanguageModelPort):
    """
    PoC adapter behavior:
    1. First final utterance per stream gets a deterministic greeting.
    2. Subsequent turns call Gemini via non-streaming `generate_content`.
    3. If provider fails, return deterministic fallback text.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        greeting_response: str = "Hi! Yes, I can hear you. The PoC mode is running correctly.",
        fallback_response: str = (
            "Hello! This is our PoC assistant. I can hear you and respond clearly. "
            "Please tell me what you would like to test next."
        ),
        system_prompt: str = (
            "You are a concise, friendly phone-call assistant for a PoC demo. "
            "Respond naturally to what the caller says in 1-3 short sentences."
        ),
    ) -> None:
        self._greeting_response = greeting_response.strip()
        self._fallback_response = fallback_response.strip()
        self._system_prompt = system_prompt
        self._model_name = model_name
        self._seen_streams: set[str] = set()
        self._client = (
            genai.Client(api_key=api_key)
            if _GENAI_AVAILABLE and api_key.strip()
            else None
        )

    async def _generate_non_streaming(self, prompt: str) -> str:
        if self._client is None:
            return ""
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=self._system_prompt),
            ),
        )
        return (response.text or "").strip()

    async def generate(
        self,
        stream_id: str,
        utterance: Utterance,
        context: list[str],
    ) -> AsyncIterator[str]:
        # First turn per call: deterministic greeting for PoC consistency.
        if stream_id not in self._seen_streams:
            self._seen_streams.add(stream_id)
            yield self._greeting_response
            return

        # Subsequent turns: use non-streaming LLM response.
        history = "\n".join(f"- {t}" for t in context[-6:]) if context else "- (no prior turns)"
        prompt = (
            "Conversation history (caller utterances):\n"
            f"{history}\n\n"
            "Current caller utterance:\n"
            f"{(utterance.text or '').strip()}\n\n"
            "Respond to the current utterance naturally."
        )

        try:
            text = await self._generate_non_streaming(prompt)
            if text:
                yield text
                return
            logger.warning("PoC non-streaming LLM returned empty text; using fallback response.")
        except Exception as exc:
            logger.warning("PoC non-streaming LLM failed; using fallback response: %s", exc)

        yield self._fallback_response
