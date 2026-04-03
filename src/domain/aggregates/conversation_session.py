"""ConversationSession aggregate - root aggregate for managing call lifecycle."""

from typing import Dict, Optional

from src.domain.entities.call_session import CallSession
from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.domain.value_objects.audio_format import AudioFormat


class ConversationSession:
    """
    Aggregate root managing the complete lifecycle of a phone conversation.
    
    Business Rule: ConversationSession is the transaction boundary and
    single point of access for all entities related to a call. External
    systems can only interact with the conversation through this aggregate root.
    """
    
    def __init__(self, call_session: CallSession) -> None:
        """
        Create a ConversationSession with an existing CallSession.
        
        Args:
            call_session: The CallSession entity (aggregate root)
        """
        self._call_session = call_session
    
    @classmethod
    def create(
        cls,
        stream_identifier: StreamIdentifier,
        caller_number: str,
        called_number: str,
        audio_format: AudioFormat,
        custom_parameters: Optional[Dict[str, str]] = None
    ) -> "ConversationSession":
        """
        Factory method to create a new ConversationSession.
        
        Args:
            stream_identifier: Unique identifier for this call stream
            caller_number: Phone number of the caller
            called_number: Phone number that was dialed
            audio_format: Audio format specification
            custom_parameters: Optional custom routing parameters
            
        Returns:
            New ConversationSession instance
        """
        call_session = CallSession(
            stream_identifier=stream_identifier,
            caller_number=caller_number,
            called_number=called_number,
            audio_format=audio_format,
            custom_parameters=custom_parameters
        )
        return cls(call_session)
    
    @property
    def call_session(self) -> CallSession:
        """Get the underlying CallSession (aggregate root entity)."""
        return self._call_session
    
    @property
    def stream_identifier(self) -> StreamIdentifier:
        """Get the unique stream identifier for this conversation."""
        return self._call_session.stream_identifier
    
    @property
    def is_ended(self) -> bool:
        """Check if the conversation has ended."""
        return self._call_session.state == "ended"
    
    def activate(self) -> None:
        """
        Activate the conversation (first audio received).
        
        Business Rule: Transitions the call from initiated to active state.
        """
        self._call_session.activate()
    
    def end(self) -> None:
        """
        End the conversation.
        
        Business Rule: Transitions the call to ended state and prevents
        further modifications.
        """
        self._call_session.end()
    
    def __eq__(self, other: object) -> bool:
        """
        Check equality based on stream_identifier (aggregate identity).
        
        Business Rule: Two ConversationSessions are the same if they
        have the same stream_identifier.
        """
        if not isinstance(other, ConversationSession):
            return False
        return self.stream_identifier == other.stream_identifier
    
    def __hash__(self) -> int:
        """Make ConversationSession hashable based on identity."""
        return hash(self.stream_identifier)
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"ConversationSession(stream_id={self.stream_identifier}, "
            f"state='{self.call_session.state}')"
        )
