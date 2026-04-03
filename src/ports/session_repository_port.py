"""SessionRepositoryPort — driven port for persisting ConversationSessions."""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.aggregates.conversation_session import ConversationSession


class SessionRepositoryPort(ABC):
    """
    Driven port for storing and retrieving ConversationSessions.

    Business Rule: Each stream_id maps to exactly one active session.
    Implementations may use in-memory dict (PoC), Redis, or a database.
    """

    @abstractmethod
    async def save(self, session: ConversationSession) -> None:
        """Persist or update a ConversationSession."""

    @abstractmethod
    async def get(self, stream_id: str) -> Optional[ConversationSession]:
        """Retrieve a session by stream_id, or None if not found."""

    @abstractmethod
    async def delete(self, stream_id: str) -> None:
        """Remove a session when the call ends."""
