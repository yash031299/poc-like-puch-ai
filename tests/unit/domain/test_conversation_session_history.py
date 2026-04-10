"""Unit tests for ConversationSession interrupt history tracking."""

import pytest
from datetime import datetime, timezone


def test_conversation_session_has_empty_interrupt_history() -> None:
    """Test that ConversationSession starts with empty interrupt history."""
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    assert conversation.interrupt_history == []


def test_conversation_session_can_record_interrupt() -> None:
    """Test that ConversationSession can record interrupt events."""
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Record first interrupt
    conversation.record_interrupt(
        token_count=5,
        context="Hello there",
        intent="early_rejection"
    )
    
    history = conversation.interrupt_history
    assert len(history) == 1
    assert history[0].token_count == 5
    assert history[0].context == "Hello there"
    assert history[0].intent == "early_rejection"
    assert isinstance(history[0].timestamp, datetime)


def test_conversation_session_interrupt_history_preserves_multiple_events() -> None:
    """Test that interrupt history accumulates multiple interrupts."""
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Record multiple interrupts
    conversation.record_interrupt(token_count=5, context="First", intent="rejection")
    conversation.record_interrupt(token_count=15, context="Second", intent="clarification")
    conversation.record_interrupt(token_count=30, context="Third", intent="question")
    
    history = conversation.interrupt_history
    assert len(history) == 3
    assert history[0].context == "First"
    assert history[1].context == "Second"
    assert history[2].context == "Third"


def test_conversation_session_interrupt_history_validates_inputs() -> None:
    """Test that interrupt recording validates inputs."""
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Negative token count
    with pytest.raises(ValueError, match="token_count cannot be negative"):
        conversation.record_interrupt(token_count=-1, context="test", intent="test")
    
    # Empty context
    with pytest.raises(ValueError, match="context cannot be empty"):
        conversation.record_interrupt(token_count=5, context="", intent="test")
    
    # Empty intent
    with pytest.raises(ValueError, match="intent cannot be empty"):
        conversation.record_interrupt(token_count=5, context="test", intent="")


def test_conversation_session_interrupt_history_max_limit() -> None:
    """Test that interrupt history has a max of 100 events to prevent memory bloat."""
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Record 100 interrupts (should succeed)
    for i in range(100):
        conversation.record_interrupt(
            token_count=i,
            context=f"Context {i}",
            intent="test"
        )
    
    assert len(conversation.interrupt_history) == 100
    
    # 101st interrupt should fail
    with pytest.raises(ValueError, match="Maximum interrupts per session"):
        conversation.record_interrupt(
            token_count=100,
            context="Over limit",
            intent="test"
        )


def test_conversation_session_interrupt_history_returns_copy() -> None:
    """Test that interrupt_history property returns a copy for immutability."""
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    conversation.record_interrupt(token_count=5, context="Test", intent="test")
    
    # Get history twice
    history1 = conversation.interrupt_history
    history2 = conversation.interrupt_history
    
    # Should be equal but not the same object
    assert history1 == history2
    assert history1 is not history2
    
    # Modifying returned list shouldn't affect internal state
    history1.clear()
    assert len(conversation.interrupt_history) == 1


def test_conversation_session_interrupt_history_preserved_on_reset_context() -> None:
    """Test that interrupt history is NOT cleared when context is reset."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.entities.utterance import Utterance
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Add interrupt history
    conversation.record_interrupt(token_count=5, context="First", intent="rejection")
    
    # Add utterance (will be cleared)
    utterance = Utterance(
        text="hello",
        confidence=0.9,
        is_final=False,
        timestamp=datetime.now(timezone.utc)
    )
    conversation.add_utterance(utterance)
    assert len(conversation.utterances) == 1
    
    # Reset context
    conversation.reset_context()
    
    # Utterances should be cleared
    assert len(conversation.utterances) == 0
    
    # But interrupt history should be preserved
    assert len(conversation.interrupt_history) == 1
    assert conversation.interrupt_history[0].context == "First"
