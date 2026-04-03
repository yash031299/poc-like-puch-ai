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
