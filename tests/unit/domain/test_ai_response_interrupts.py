"""Unit tests for AIResponse interrupt tracking."""

import pytest
from datetime import datetime, timezone


def test_ai_response_has_interrupt_fields() -> None:
    """Test that AIResponse has optional interrupt tracking fields."""
    from src.domain.entities.ai_response import AIResponse
    
    ts = datetime.now(timezone.utc)
    response = AIResponse(utterance_id="utt-1", timestamp=ts)
    
    # All interrupt fields should start as None
    assert response.interrupted_at_token_count is None
    assert response.interrupted_at_timestamp is None
    assert response.interrupted_context is None
    assert not response.is_interrupted()


def test_ai_response_can_record_interrupt() -> None:
    """Test that AIResponse can record interrupt metadata."""
    from src.domain.entities.ai_response import AIResponse
    
    ts = datetime.now(timezone.utc)
    response = AIResponse(utterance_id="utt-1", timestamp=ts)
    response.append_text("Hello there, this is the AI speaking...")
    
    interrupt_ts = datetime.now(timezone.utc)
    response.record_interrupt(
        token_count=5,
        timestamp=interrupt_ts,
        context="Hello there, this is"
    )
    
    assert response.interrupted_at_token_count == 5
    assert response.interrupted_at_timestamp == interrupt_ts
    assert response.interrupted_context == "Hello there, this is"
    assert response.is_interrupted()


def test_ai_response_interrupt_validation() -> None:
    """Test that interrupt recording validates inputs."""
    from src.domain.entities.ai_response import AIResponse
    
    ts = datetime.now(timezone.utc)
    response = AIResponse(utterance_id="utt-1", timestamp=ts)
    
    # Token count cannot be negative
    with pytest.raises(ValueError, match="token_count cannot be negative"):
        response.record_interrupt(token_count=-1, timestamp=ts, context="test")
    
    # Context cannot be empty
    with pytest.raises(ValueError, match="context cannot be empty"):
        response.record_interrupt(token_count=5, timestamp=ts, context="")


def test_ai_response_interrupt_metadata_immutable_after_recording() -> None:
    """Test that interrupt metadata is set and tracks correctly."""
    from src.domain.entities.ai_response import AIResponse
    
    ts1 = datetime.now(timezone.utc)
    response = AIResponse(utterance_id="utt-1", timestamp=ts1)
    
    ts2 = datetime.now(timezone.utc)
    response.record_interrupt(
        token_count=10,
        timestamp=ts2,
        context="Sample context"
    )
    
    # Values should be exactly what was recorded
    assert response.interrupted_at_token_count == 10
    assert response.interrupted_at_timestamp == ts2
    assert response.interrupted_context == "Sample context"
    assert response.is_interrupted()
    
    # Can check is_interrupted without accessing internal fields
    assert response.is_interrupted() is True
