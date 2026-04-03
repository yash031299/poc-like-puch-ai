"""Unit tests for Utterance entity."""

import pytest
from datetime import datetime, timezone


def test_utterance_can_be_created() -> None:
    """Test that an Utterance can be created with required attributes."""
    from src.domain.entities.utterance import Utterance
    
    timestamp = datetime.now(timezone.utc)
    
    utterance = Utterance(
        text="Hello, can you help me?",
        confidence=0.95,
        is_final=True,
        timestamp=timestamp
    )
    
    assert utterance is not None
    assert utterance.text == "Hello, can you help me?"
    assert utterance.confidence == 0.95
    assert utterance.is_final is True
    assert utterance.timestamp == timestamp


def test_utterance_validates_non_empty_text() -> None:
    """Test that utterance text cannot be empty."""
    from src.domain.entities.utterance import Utterance
    
    timestamp = datetime.now(timezone.utc)
    
    # Empty text should raise error
    with pytest.raises(ValueError, match="Utterance text cannot be empty"):
        Utterance(
            text="",
            confidence=0.95,
            is_final=True,
            timestamp=timestamp
        )
    
    # Whitespace-only text should also raise error
    with pytest.raises(ValueError, match="Utterance text cannot be empty"):
        Utterance(
            text="   ",
            confidence=0.95,
            is_final=True,
            timestamp=timestamp
        )


def test_utterance_validates_confidence_range() -> None:
    """Test that confidence must be between 0.0 and 1.0."""
    from src.domain.entities.utterance import Utterance
    
    timestamp = datetime.now(timezone.utc)
    
    # Confidence below 0 should raise error
    with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
        Utterance(
            text="Hello",
            confidence=-0.1,
            is_final=True,
            timestamp=timestamp
        )
    
    # Confidence above 1 should raise error
    with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
        Utterance(
            text="Hello",
            confidence=1.5,
            is_final=True,
            timestamp=timestamp
        )
    
    # Confidence at boundaries should be OK
    utterance_zero = Utterance(text="Hello", confidence=0.0, is_final=True, timestamp=timestamp)
    assert utterance_zero.confidence == 0.0
    
    utterance_one = Utterance(text="Hello", confidence=1.0, is_final=True, timestamp=timestamp)
    assert utterance_one.confidence == 1.0


def test_utterance_partial_vs_final() -> None:
    """Test that utterances can be marked as partial or final."""
    from src.domain.entities.utterance import Utterance
    
    timestamp = datetime.now(timezone.utc)
    
    # Partial utterance (in-progress speech)
    partial = Utterance(
        text="What is",
        confidence=0.8,
        is_final=False,
        timestamp=timestamp
    )
    
    assert partial.is_final is False
    assert partial.is_partial is True
    
    # Final utterance (completed speech)
    final = Utterance(
        text="What is the weather today?",
        confidence=0.95,
        is_final=True,
        timestamp=timestamp
    )
    
    assert final.is_final is True
    assert final.is_partial is False


def test_utterance_can_be_updated() -> None:
    """Test that partial utterances can be updated with more text."""
    from src.domain.entities.utterance import Utterance
    
    timestamp = datetime.now(timezone.utc)
    
    # Start with partial utterance
    utterance = Utterance(
        text="What is",
        confidence=0.8,
        is_final=False,
        timestamp=timestamp
    )
    
    assert utterance.text == "What is"
    assert utterance.is_partial is True
    
    # Update with more text
    utterance.update_text("What is the weather", confidence=0.85)
    
    assert utterance.text == "What is the weather"
    assert utterance.confidence == 0.85
    assert utterance.is_partial is True  # Still partial
    
    # Finalize the utterance
    utterance.finalize("What is the weather today?", confidence=0.95)
    
    assert utterance.text == "What is the weather today?"
    assert utterance.confidence == 0.95
    assert utterance.is_final is True


def test_utterance_cannot_update_final() -> None:
    """Test that final utterances cannot be updated."""
    from src.domain.entities.utterance import Utterance
    
    timestamp = datetime.now(timezone.utc)
    
    utterance = Utterance(
        text="Hello there",
        confidence=0.95,
        is_final=True,
        timestamp=timestamp
    )
    
    # Attempting to update final utterance should raise error
    with pytest.raises(ValueError, match="Cannot update a final utterance"):
        utterance.update_text("Hello there friend", confidence=0.96)
    
    with pytest.raises(ValueError, match="Cannot finalize an already final utterance"):
        utterance.finalize("Hello there friend", confidence=0.96)


def test_utterance_has_unique_id() -> None:
    """Test that each utterance has a unique identifier."""
    from src.domain.entities.utterance import Utterance
    
    timestamp = datetime.now(timezone.utc)
    
    utterance1 = Utterance(
        text="Hello",
        confidence=0.95,
        is_final=True,
        timestamp=timestamp
    )
    
    utterance2 = Utterance(
        text="Hello",  # Same text
        confidence=0.95,  # Same confidence
        is_final=True,
        timestamp=timestamp
    )
    
    # Each utterance should have unique ID
    assert utterance1.utterance_id != utterance2.utterance_id
    
    # IDs should not be None
    assert utterance1.utterance_id is not None
    assert utterance2.utterance_id is not None


def test_utterance_equality_based_on_id() -> None:
    """Test that utterances are equal if they have the same ID."""
    from src.domain.entities.utterance import Utterance
    
    timestamp = datetime.now(timezone.utc)
    
    utterance1 = Utterance(
        text="Hello",
        confidence=0.95,
        is_final=True,
        timestamp=timestamp
    )
    
    utterance2 = Utterance(
        text="Goodbye",
        confidence=0.85,
        is_final=False,
        timestamp=timestamp
    )
    
    # Different utterances are not equal
    assert utterance1 != utterance2
    
    # Same utterance is equal to itself
    assert utterance1 == utterance1


def test_utterance_string_representation() -> None:
    """Test that Utterance has a useful string representation."""
    from src.domain.entities.utterance import Utterance
    
    timestamp = datetime.now(timezone.utc)
    
    utterance = Utterance(
        text="Hello world",
        confidence=0.92,
        is_final=True,
        timestamp=timestamp
    )
    
    repr_str = repr(utterance)
    assert "Utterance" in repr_str
    assert "Hello world" in repr_str
    assert "0.92" in repr_str
    assert "final" in repr_str
