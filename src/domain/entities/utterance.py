"""Utterance entity - represents transcribed speech from caller."""

import uuid
from datetime import datetime


class Utterance:
    """
    Entity representing a transcribed segment of caller speech.
    
    Business Rule: Utterances can be partial (in-progress) or final (complete).
    Partial utterances can be updated as more speech is received.
    Final utterances are immutable.
    """

    __slots__ = ("_utterance_id", "_text", "_confidence", "_is_final", "_timestamp")

    def __init__(
        self,
        text: str,
        confidence: float,
        is_final: bool,
        timestamp: datetime
    ) -> None:
        """
        Create an Utterance.
        
        Args:
            text: Transcribed text (must not be empty)
            confidence: Confidence score 0.0 to 1.0
            is_final: True if speech is complete, False if still in progress
            timestamp: When the utterance was created/transcribed
            
        Raises:
            ValueError: If text is empty or confidence is out of range
        """
        if not text or not text.strip():
            raise ValueError("Utterance text cannot be empty")
        
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        
        self._utterance_id = str(uuid.uuid4())
        self._text = text
        self._confidence = confidence
        self._is_final = is_final
        self._timestamp = timestamp
    
    @property
    def utterance_id(self) -> str:
        """Get the unique identifier for this utterance."""
        return self._utterance_id
    
    @property
    def text(self) -> str:
        """Get the transcribed text."""
        return self._text
    
    @property
    def confidence(self) -> float:
        """Get the confidence score (0.0 to 1.0)."""
        return self._confidence
    
    @property
    def is_final(self) -> bool:
        """Check if the utterance is final (complete)."""
        return self._is_final
    
    @property
    def is_partial(self) -> bool:
        """Check if the utterance is partial (in-progress)."""
        return not self._is_final
    
    @property
    def timestamp(self) -> datetime:
        """Get the timestamp when utterance was created."""
        return self._timestamp
    
    def update_text(self, new_text: str, confidence: float) -> None:
        """
        Update the utterance text (only for partial utterances).
        
        Business Rule: Only partial utterances can be updated.
        Final utterances are immutable.
        
        Args:
            new_text: Updated transcribed text
            confidence: Updated confidence score
            
        Raises:
            ValueError: If utterance is final or text is empty
        """
        if self._is_final:
            raise ValueError("Cannot update a final utterance")
        
        if not new_text or not new_text.strip():
            raise ValueError("Utterance text cannot be empty")
        
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        
        self._text = new_text
        self._confidence = confidence
    
    def finalize(self, final_text: str, confidence: float) -> None:
        """
        Finalize the utterance with the complete transcribed text.
        
        Business Rule: Once finalized, an utterance cannot be modified.
        
        Args:
            final_text: Final complete transcribed text
            confidence: Final confidence score
            
        Raises:
            ValueError: If already final or text is empty
        """
        if self._is_final:
            raise ValueError("Cannot finalize an already final utterance")
        
        if not final_text or not final_text.strip():
            raise ValueError("Utterance text cannot be empty")
        
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        
        self._text = final_text
        self._confidence = confidence
        self._is_final = True
    
    def __eq__(self, other: object) -> bool:
        """
        Check equality based on utterance_id (entity identity).
        
        Business Rule: Two Utterances are the same if they have
        the same utterance_id.
        """
        if not isinstance(other, Utterance):
            return False
        return self._utterance_id == other._utterance_id
    
    def __hash__(self) -> int:
        """Make Utterance hashable based on identity."""
        return hash(self._utterance_id)
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        status = "final" if self._is_final else "partial"
        # Truncate long text for readability
        display_text = self._text if len(self._text) <= 30 else f"{self._text[:27]}..."
        return (
            f"Utterance('{display_text}', "
            f"confidence={self._confidence:.2f}, "
            f"{status})"
        )
