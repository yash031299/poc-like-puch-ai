"""InMemorySessionRepository — dict-backed implementation for PoC."""

from typing import Dict, Optional

from src.domain.aggregates.conversation_session import ConversationSession
from src.ports.session_repository_port import SessionRepositoryPort


class InMemorySessionRepository(SessionRepositoryPort):
    """
    In-memory implementation of SessionRepositoryPort.

    PoC-grade: stores sessions in a plain dict. No persistence across
    restarts. Suitable for single-process deployments and tests.

    For production: replace with RedisSessionRepository or similar.
    """

    def __init__(self) -> None:
        self._store: Dict[str, ConversationSession] = {}

    async def save(self, session: ConversationSession) -> None:
        self._store[session.stream_identifier.value] = session

    async def get(self, stream_id: str) -> Optional[ConversationSession]:
        return self._store.get(stream_id)

    async def delete(self, stream_id: str) -> None:
        self._store.pop(stream_id, None)

    def __len__(self) -> int:
        """Number of active sessions (useful for monitoring)."""
        return len(self._store)
