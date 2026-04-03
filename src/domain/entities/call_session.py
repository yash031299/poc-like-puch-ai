"""CallSession entity - represents an active phone call."""

from datetime import datetime, timezone
from typing import Dict, Optional

from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.domain.value_objects.audio_format import AudioFormat


class CallSession:
    """
    Entity representing an active telephone conversation.
    
    Business Rule: A CallSession represents a phone call with unique identity,
    mutable state, and a lifecycle from initiated → active → ended.
    """
    
    def __init__(
        self,
        stream_identifier: StreamIdentifier,
        caller_number: str,
        called_number: str,
        audio_format: AudioFormat,
        custom_parameters: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Create a new CallSession.
        
        Args:
            stream_identifier: Unique identifier for this call stream
            caller_number: Phone number of the caller
            called_number: Phone number that was dialed
            audio_format: Audio format specification for this call
            custom_parameters: Optional custom routing parameters
        """
        self._stream_identifier = stream_identifier
        self._caller_number = caller_number
        self._called_number = called_number
        self._audio_format = audio_format
        self._custom_parameters = custom_parameters or {}
        
        # Initialize state
        self._state = "initiated"
        self._started_at = datetime.now(timezone.utc)
        self._ended_at: Optional[datetime] = None
    
    @property
    def stream_identifier(self) -> StreamIdentifier:
        """Get the unique stream identifier."""
        return self._stream_identifier
    
    @property
    def caller_number(self) -> str:
        """Get the caller's phone number."""
        return self._caller_number
    
    @property
    def called_number(self) -> str:
        """Get the dialed phone number."""
        return self._called_number
    
    @property
    def audio_format(self) -> AudioFormat:
        """Get the audio format for this call."""
        return self._audio_format
    
    @property
    def custom_parameters(self) -> Dict[str, str]:
        """Get custom routing parameters."""
        return self._custom_parameters.copy()  # Return copy to prevent external modification
    
    @property
    def state(self) -> str:
        """Get current call state (initiated, active, ended)."""
        return self._state
    
    @property
    def started_at(self) -> datetime:
        """Get the timestamp when call was initiated."""
        return self._started_at
    
    @property
    def ended_at(self) -> Optional[datetime]:
        """Get the timestamp when call ended (None if still active)."""
        return self._ended_at
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """
        Calculate call duration in seconds.
        
        Returns:
            Duration in seconds, or None if call hasn't ended
        """
        if self._ended_at is None:
            return None
        
        delta = self._ended_at - self._started_at
        return delta.total_seconds()
    
    def activate(self) -> None:
        """
        Transition call to active state (first audio received).
        
        Raises:
            ValueError: If call is already ended
        """
        if self._state == "ended":
            raise ValueError("Cannot activate ended call")
        
        self._state = "active"
    
    def end(self) -> None:
        """Transition call to ended state."""
        self._state = "ended"
        self._ended_at = datetime.now(timezone.utc)
    
    def __eq__(self, other: object) -> bool:
        """
        Check equality based on stream_identifier (entity identity).
        
        Business Rule: Two CallSessions are the same if they have
        the same stream_identifier, regardless of other attributes.
        """
        if not isinstance(other, CallSession):
            return False
        return self.stream_identifier == other.stream_identifier
    
    def __hash__(self) -> int:
        """Make CallSession hashable based on identity."""
        return hash(self.stream_identifier)
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"CallSession(stream_id={self.stream_identifier}, "
            f"state='{self.state}', caller={self.caller_number})"
        )
