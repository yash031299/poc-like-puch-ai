"""AIResponse entity - AI-generated reply to caller's utterance."""

import uuid
from datetime import datetime

_VALID_STATES = ("generating", "complete", "delivered")


class AIResponse:
    """
    Entity representing the AI agent's response to a caller utterance.

    Business Rule: Responses are streamed token-by-token during generation.
    Once complete they are immutable; once delivered they are fully consumed.

    States: generating → complete → delivered
    """

    def __init__(self, utterance_id: str, timestamp: datetime) -> None:
        if not utterance_id or not utterance_id.strip():
            raise ValueError("utterance_id cannot be empty")

        self._response_id: str = str(uuid.uuid4())
        self._utterance_id: str = utterance_id
        self._timestamp: datetime = timestamp
        self._text: str = ""
        self._state: str = "generating"

    # --- Identity / read ---

    @property
    def response_id(self) -> str:
        return self._response_id

    @property
    def utterance_id(self) -> str:
        return self._utterance_id

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    @property
    def text(self) -> str:
        return self._text

    @property
    def state(self) -> str:
        return self._state

    # --- Mutations ---

    def append_text(self, token: str) -> None:
        """Append a streaming token. Only allowed while generating."""
        if self._state != "generating":
            raise ValueError("Cannot append to a complete response")
        self._text += token

    def complete(self) -> None:
        """Mark response as fully generated. Requires non-empty text."""
        if not self._text.strip():
            raise ValueError("Cannot complete a response with no text")
        self._state = "complete"

    def mark_delivered(self) -> None:
        """Mark response as delivered to caller. Requires complete state."""
        if self._state != "complete":
            raise ValueError("Cannot deliver a response that is not complete")
        self._state = "delivered"

    # --- Identity ---

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AIResponse):
            return False
        return self._response_id == other._response_id

    def __hash__(self) -> int:
        return hash(self._response_id)

    def __repr__(self) -> str:
        snippet = self._text[:30] + "..." if len(self._text) > 30 else self._text
        return f"AIResponse('{snippet}', state='{self._state}')"
