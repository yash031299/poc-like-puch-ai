"""Unit tests for ConversationSession aggregate."""

import pytest


def test_conversation_session_can_be_created() -> None:
    """Test that ConversationSession can be created with a CallSession."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    from src.domain.aggregates.conversation_session import ConversationSession
    
    call_session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    # Act
    conversation = ConversationSession(call_session)
    
    # Assert
    assert conversation.call_session == call_session
    assert conversation.stream_identifier == call_session.stream_identifier


def test_conversation_session_provides_access_to_call_session() -> None:
    """Test that ConversationSession provides access to underlying CallSession."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    from src.domain.aggregates.conversation_session import ConversationSession
    
    call_session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    conversation = ConversationSession(call_session)
    
    # Assert - Can access CallSession properties through aggregate
    assert conversation.call_session.state == "initiated"
    assert conversation.call_session.caller_number == "+1234567890"


def test_conversation_session_can_activate_call() -> None:
    """Test that ConversationSession can activate the underlying call."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    from src.domain.aggregates.conversation_session import ConversationSession
    
    call_session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    conversation = ConversationSession(call_session)
    
    # Act
    conversation.activate()
    
    # Assert
    assert conversation.call_session.state == "active"


def test_conversation_session_can_end_call() -> None:
    """Test that ConversationSession can end the underlying call."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    from src.domain.aggregates.conversation_session import ConversationSession
    
    call_session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    conversation = ConversationSession(call_session)
    
    # Act
    conversation.end()
    
    # Assert
    assert conversation.call_session.state == "ended"
    assert conversation.is_ended


def test_conversation_session_equality_based_on_stream_identifier() -> None:
    """Test that ConversationSession equality is based on stream_identifier."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    from src.domain.aggregates.conversation_session import ConversationSession
    
    stream_id = StreamIdentifier("stream-123")
    
    call1 = CallSession(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    call2 = CallSession(
        stream_identifier=stream_id,
        caller_number="+9999999999",
        called_number="+1111111111",
        audio_format=AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)
    )
    
    conv1 = ConversationSession(call1)
    conv2 = ConversationSession(call2)
    
    # Assert - Same stream_identifier means same conversation
    assert conv1 == conv2


def test_conversation_session_is_ended_property() -> None:
    """Test that ConversationSession has is_ended convenience property."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    from src.domain.aggregates.conversation_session import ConversationSession
    
    call_session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    conversation = ConversationSession(call_session)
    
    # Assert - Not ended initially
    assert not conversation.is_ended
    
    # End conversation
    conversation.end()
    
    # Assert - Now ended
    assert conversation.is_ended


def test_conversation_session_factory_method() -> None:
    """Test that ConversationSession can be created via factory method."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.aggregates.conversation_session import ConversationSession
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    # Act
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Assert
    assert conversation.stream_identifier == stream_id
    assert conversation.call_session.caller_number == "+1234567890"
    assert conversation.call_session.state == "initiated"


def test_conversation_session_factory_with_custom_parameters() -> None:
    """Test that factory method supports custom parameters."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.aggregates.conversation_session import ConversationSession
    
    custom_params = {"language": "en-US", "department": "sales"}
    
    # Act
    conversation = ConversationSession.create(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
        custom_parameters=custom_params
    )
    
    # Assert
    assert conversation.call_session.custom_parameters == custom_params


def test_conversation_session_mark_interrupted() -> None:
    """Test that ConversationSession can be marked as interrupted."""
    # Arrange
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Assert - Not interrupted initially
    assert not conversation.is_interrupted()
    
    # Act - Mark as interrupted
    conversation.mark_interrupted()
    
    # Assert - Now interrupted
    assert conversation.is_interrupted()


def test_conversation_session_reset_interrupt() -> None:
    """Test that ConversationSession can reset interrupt flag."""
    # Arrange
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Act - Mark as interrupted then reset
    conversation.mark_interrupted()
    assert conversation.is_interrupted()
    
    conversation.reset_interrupt()
    
    # Assert - Flag is reset
    assert not conversation.is_interrupted()


def test_conversation_session_mark_interrupted_changes_state_to_listening() -> None:
    """Test that marking interrupted changes interaction state to listening."""
    # Arrange
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Act - Set to speaking, then interrupt
    conversation.set_speaking()
    assert conversation.interaction_state == "speaking"
    
    conversation.mark_interrupted()
    
    # Assert - State changed to listening
    assert conversation.interaction_state == "listening"


def test_conversation_session_interrupt_timestamp_recorded() -> None:
    """Test that interrupt timestamp is recorded when interrupted."""
    # Arrange
    from src.domain.aggregates.conversation_session import ConversationSession
    from datetime import datetime, timezone
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Act - Mark as interrupted
    before = datetime.now(timezone.utc)
    conversation.mark_interrupted()
    after = datetime.now(timezone.utc)
    
    # Assert - Timestamp is recorded and within expected range
    assert conversation._interrupt_timestamp is not None
    assert before <= conversation._interrupt_timestamp <= after


def test_conversation_session_cannot_interrupt_ended_session() -> None:
    """Test that interrupting an ended session doesn't change its state."""
    # Arrange
    from src.domain.aggregates.conversation_session import ConversationSession
    
    conversation = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Act - End the conversation
    conversation.end()
    assert conversation.is_ended
    
    # Try to interrupt (should not change anything)
    conversation.mark_interrupted()
    
    # Assert - Still ended, interrupt flag not set (because of the check in mark_interrupted)
    assert conversation.is_ended
    assert not conversation.is_interrupted()
