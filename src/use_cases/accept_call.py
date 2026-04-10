"""AcceptCallUseCase — create and activate a ConversationSession on call arrival."""

from typing import Dict, Optional

from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.value_objects.audio_format import AudioFormat
from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.ports.session_repository_port import SessionRepositoryPort
from src.infrastructure.tracing import traced_use_case


class AcceptCallUseCase:
    """
    Application use case: Accept an incoming phone call.

    Orchestrates:
    1. Check for duplicate stream
    2. Create ConversationSession
    3. Activate the call (mark stream as live)
    4. Persist to repository
    5. Return session to caller (adapter)

    This class has NO infrastructure knowledge — it depends only on ports.
    """

    def __init__(self, session_repo: SessionRepositoryPort) -> None:
        self._repo = session_repo

    @traced_use_case
    async def execute(
        self,
        stream_id: str,
        caller_number: str,
        called_number: str,
        audio_format: AudioFormat,
        custom_parameters: Optional[Dict[str, str]] = None,
    ) -> ConversationSession:
        """
        Accept an incoming call and return the active session.

        Args:
            stream_id: Unique stream identifier from Exotel
            caller_number: Phone number of the caller
            called_number: Phone number that was dialed
            audio_format: Audio format specification
            custom_parameters: Optional routing parameters from Exotel

        Returns:
            The newly created and active ConversationSession

        Raises:
            ValueError: If a session for this stream_id already exists
        """
        # Business Rule: each stream_id maps to exactly one session
        existing = await self._repo.get(stream_id)
        if existing is not None:
            raise ValueError(f"Session already exists for stream {stream_id}")

        session = ConversationSession.create(
            stream_identifier=StreamIdentifier(stream_id),
            caller_number=caller_number,
            called_number=called_number,
            audio_format=audio_format,
            custom_parameters=custom_parameters,
        )

        # Activate: stream is live, ready to receive audio
        session.activate()

        await self._repo.save(session)
        return session
