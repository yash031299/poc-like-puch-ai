"""Unit tests for StreamIdentifier value object."""

import pytest


def test_stream_identifier_can_be_created_with_value() -> None:
    """Test that StreamIdentifier can be created with a string value."""
    # Arrange
    value = "stream-123-abc"
    
    # Act
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    identifier = StreamIdentifier(value)
    
    # Assert
    assert identifier.value == value


def test_stream_identifier_is_immutable() -> None:
    """Test that StreamIdentifier value cannot be changed after creation."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    identifier = StreamIdentifier("stream-123")
    
    # Act & Assert
    with pytest.raises(AttributeError):
        identifier.value = "different-value"  # type: ignore


def test_stream_identifier_equality() -> None:
    """Test that two StreamIdentifiers with same value are equal."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    id1 = StreamIdentifier("stream-123")
    id2 = StreamIdentifier("stream-123")
    id3 = StreamIdentifier("stream-456")
    
    # Assert
    assert id1 == id2
    assert id1 != id3


def test_stream_identifier_cannot_be_empty() -> None:
    """Test that StreamIdentifier cannot be created with empty value."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    
    # Act & Assert
    with pytest.raises(ValueError, match="cannot be empty"):
        StreamIdentifier("")


def test_stream_identifier_string_representation() -> None:
    """Test that StreamIdentifier has meaningful string representation."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    identifier = StreamIdentifier("stream-123")
    
    # Assert
    assert str(identifier) == "stream-123"
    assert repr(identifier) == "StreamIdentifier('stream-123')"
