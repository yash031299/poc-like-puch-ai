"""StreamResponseUseCase — synthesize AIResponse and stream audio to caller."""

from src.ports.session_repository_port import SessionRepositoryPort
from src.ports.text_to_speech_port import TextToSpeechPort
from src.ports.caller_audio_port import CallerAudioPort


class StreamResponseUseCase:
    """
    Application use case: Synthesize AI response and stream audio to caller.

    Orchestrates:
    1. Load session from repo
    2. Find the AIResponse by ID
    3. Stream synthesis through TTS port
    4. For each SpeechSegment: store in session + send via CallerAudioPort
    5. Mark AIResponse as delivered
    6. Persist session
    """

    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        tts: TextToSpeechPort,
        audio_out: CallerAudioPort,
    ) -> None:
        self._repo = session_repo
        self._tts = tts
        self._audio_out = audio_out

    async def execute(self, stream_id: str, response_id: str) -> None:
        session = await self._repo.get(stream_id)
        if session is None:
            raise ValueError(f"No active session for stream {stream_id}")

        response = next(
            (r for r in session.ai_responses if r.response_id == response_id), None
        )
        if response is None:
            raise ValueError(f"AIResponse {response_id} not found in session {stream_id}")

        async for segment in self._tts.synthesize(stream_id, response):
            session.add_speech_segment(segment)
            await self._audio_out.send_segment(stream_id, segment)

        response.mark_delivered()
        await self._repo.save(session)
