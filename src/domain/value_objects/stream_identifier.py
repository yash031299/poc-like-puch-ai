"""StreamIdentifier value object - immutable unique identifier for call streams."""

from typing import Any


class StreamIdentifier:
    """
    Immutable unique identifier for a call stream.
    
    Business Rule: A StreamIdentifier uniquely identifies a call stream
    for its entire lifecycle and cannot be changed.
    """
    
    def __init__(self, value: str) -> None:
        """
        Create a new StreamIdentifier.
        
        Args:
            value: The unique identifier string
            
        Raises:
            ValueError: If value is empty
        """
        if not value:
            raise ValueError("StreamIdentifier value cannot be empty")
        
        # Use object.__setattr__ to set value on immutable object
        object.__setattr__(self, "_value", value)
    
    @property
    def value(self) -> str:
        """Get the identifier value."""
        return self._value  # type: ignore
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent attribute modification (immutability)."""
        raise AttributeError("StreamIdentifier is immutable")
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on value."""
        if not isinstance(other, StreamIdentifier):
            return False
        return self.value == other.value
    
    def __hash__(self) -> int:
        """Make StreamIdentifier hashable (can be used in sets/dicts)."""
        return hash(self.value)
    
    def __str__(self) -> str:
        """String representation."""
        return self.value
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return f"StreamIdentifier('{self.value}')"
