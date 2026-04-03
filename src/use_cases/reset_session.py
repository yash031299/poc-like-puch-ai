"""ResetSessionUseCase — clear conversation context when Exotel sends 'clear' event."""

from src.ports.session_repository_port import SessionRepositoryPort


class ResetSessionUseCase:
    """
    Application use case: Reset mid-call conversation context.

    Triggered when Exotel sends an inbound 'clear' event, which happens
    when the caller says 'start over' or context needs to be flushed.

    Orchestrates:
    1. Load session from repo
    2. Call reset_context() on the ConversationSession (domain logic)
    3. Persist the cleared session

    What is cleared: utterances, AI responses, speech segments
    What is preserved: audio chunks, call state, caller info
    """

    def __init__(self, session_repo: SessionRepositoryPort) -> None:
        self._repo = session_repo

    async def execute(self, stream_id: str) -> None:
        session = await self._repo.get(stream_id)
        if session is None:
            raise ValueError(f"No active session for stream {stream_id}")

        session.reset_context()
        await self._repo.save(session)
