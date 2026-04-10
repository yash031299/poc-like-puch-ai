"""EndCallUseCase — terminate the call and clean up the session."""

from src.ports.session_repository_port import SessionRepositoryPort
from src.infrastructure.tracing import traced_use_case


class EndCallUseCase:
    """
    Application use case: End an active phone call.

    Orchestrates:
    1. Load session from repo
    2. End the ConversationSession (enforces business rules)
    3. Delete session from repo (call is over)
    """

    def __init__(self, session_repo: SessionRepositoryPort) -> None:
        self._repo = session_repo

    @traced_use_case

    async def execute(self, stream_id: str) -> None:
        session = await self._repo.get(stream_id)
        if session is None:
            raise ValueError(f"No active session for stream {stream_id}")

        session.end()
        await self._repo.delete(stream_id)
