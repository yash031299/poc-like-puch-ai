"""ProcessAudioUseCase — receive audio chunk, transcribe, update session."""

from typing import List

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance
from src.ports.session_repository_port import SessionRepositoryPort
from src.ports.speech_to_text_port import SpeechToTextPort


class ProcessAudioUseCase:
    """
    Application use case: Process an incoming audio chunk from caller.

    Orchestrates:
    1. Load session from repo
    2. Add audio chunk to session
    3. Stream chunk through STT port
    4. Collect partial + final utterances, store in session
    5. Persist updated session
    6. Return list of utterances produced
    """

    def __init__(self, session_repo: SessionRepositoryPort, stt: SpeechToTextPort) -> None:
        self._repo = session_repo
        self._stt = stt

    async def execute(self, stream_id: str, chunk: AudioChunk) -> List[Utterance]:
        session = await self._repo.get(stream_id)
        if session is None:
            raise ValueError(f"No active session for stream {stream_id}")

        session.add_audio_chunk(chunk)

        utterances: List[Utterance] = []
        async for utterance in self._stt.transcribe(stream_id, chunk):
            session.add_utterance(utterance)
            utterances.append(utterance)

        await self._repo.save(session)
        return utterances
