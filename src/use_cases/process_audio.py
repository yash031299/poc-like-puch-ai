"""ProcessAudioUseCase — receive audio chunk, transcribe, and trigger AI pipeline."""

import logging
from typing import List, Optional

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance
from src.ports.session_repository_port import SessionRepositoryPort
from src.ports.speech_to_text_port import SpeechToTextPort

logger = logging.getLogger(__name__)


class ProcessAudioUseCase:
    """
    Application use case: Process an incoming audio chunk from caller.

    Orchestrates:
    1. Load session from repo
    2. Add audio chunk to session
    3. Stream chunk through STT port
    4. For each final utterance: trigger GenerateResponse → StreamResponse
    5. Persist updated session
    6. Return list of utterances produced

    Optional generate_response and stream_response use cases close the
    full pipeline (STT → LLM → TTS → caller).
    """

    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        stt: SpeechToTextPort,
        generate_response=None,
        stream_response=None,
    ) -> None:
        self._repo = session_repo
        self._stt = stt
        self._generate = generate_response
        self._stream = stream_response

    async def execute(self, stream_id: str, chunk: AudioChunk) -> List[Utterance]:
        session = await self._repo.get(stream_id)
        if session is None:
            raise ValueError(f"No active session for stream {stream_id}")

        session.add_audio_chunk(chunk)

        utterances: List[Utterance] = []
        async for utterance in self._stt.transcribe(stream_id, chunk):
            session.add_utterance(utterance)
            utterances.append(utterance)

            # Trigger AI pipeline only on final utterances
            if utterance.is_final and self._generate and self._stream:
                try:
                    response = await self._generate.execute(
                        stream_id=stream_id,
                        utterance_id=utterance.utterance_id,
                    )
                    await self._stream.execute(
                        stream_id=stream_id,
                        response_id=response.response_id,
                    )
                except Exception as exc:
                    logger.error("AI pipeline failed stream=%s: %s", stream_id, exc)

        await self._repo.save(session)
        return utterances

