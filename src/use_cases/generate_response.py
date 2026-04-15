"""GenerateResponseUseCase — call LLM and build AIResponse from streamed tokens."""

from src.domain.entities.ai_response import AIResponse
from src.ports.session_repository_port import SessionRepositoryPort
import logging
from src.ports.language_model_port import LanguageModelPort
from src.infrastructure.tracing import traced_use_case

logger = logging.getLogger(__name__)


class GenerateResponseUseCase:
    """
    Application use case: Generate an AI response for a caller's utterance.

    Orchestrates:
    1. Load session from repo
    2. Find the utterance by ID
    3. Build conversation context (prior final utterances)
    4. Stream tokens from LLM port into AIResponse
    5. Complete the response
    6. Store in session and persist
    7. Return the complete AIResponse
    """

    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        llm: LanguageModelPort,
        degraded_response_text: str = (
            "I am having trouble right now. Please try again in a moment."
        ),
    ) -> None:
        self._repo = session_repo
        self._llm = llm
        self._degraded_response_text = (degraded_response_text or "").strip()

    @traced_use_case

    async def execute(self, stream_id: str, utterance_id: str) -> AIResponse:
        from datetime import datetime, timezone

        session = await self._repo.get(stream_id)
        if session is None:
            raise ValueError(f"No active session for stream {stream_id}")

        # Find the utterance
        utterance = next(
            (u for u in session.utterances if u.utterance_id == utterance_id), None
        )
        if utterance is None:
            raise ValueError(f"Utterance {utterance_id} not found in session {stream_id}")

        # Build context from prior final turns
        context = [u.text for u in session.final_utterances if u.utterance_id != utterance_id]

        logger.info("Generating AI response for stream=%s utterance=%s", stream_id, utterance_id)
        # Stream tokens and build response
        response = AIResponse(utterance_id=utterance_id, timestamp=datetime.now(timezone.utc))
        token_count = 0
        try:
            async for token in self._llm.generate(stream_id, utterance, context):
                response.append_text(token)
                token_count += 1
        except Exception as exc:
            logger.error(
                "LLM generation failed stream=%s utterance=%s: %s",
                stream_id,
                utterance_id,
                exc,
                exc_info=True,
            )
            if token_count == 0 and self._degraded_response_text:
                logger.warning(
                    "Using degraded response text for stream=%s utterance=%s",
                    stream_id,
                    utterance_id,
                )
                response.append_text(self._degraded_response_text)
            else:
                raise

        response.complete()
        session.add_ai_response(response)

        await self._repo.save(session)
        logger.info("AI response generated for stream=%s response_id=%s", stream_id, response.response_id)
        return response
