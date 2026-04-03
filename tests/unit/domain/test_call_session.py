"""Unit tests for CallSession entity."""

import pytest
from datetime import datetime, timezone


def test_call_session_can_be_created() -> None:
    """Test that CallSession can be created with required parameters."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    # Act
    session = CallSession(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Assert
    assert session.stream_identifier == stream_id
    assert session.caller_number == "+1234567890"
    assert session.called_number == "+0987654321"
    assert session.audio_format == audio_format
    assert session.state == "initiated"
    assert session.started_at is not None


def test_call_session_starts_in_initiated_state() -> None:
    """Test that new CallSession starts in 'initiated' state."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    # Act
    session = CallSession(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Assert
    assert session.state == "initiated"


def test_call_session_can_transition_to_active() -> None:
    """Test that CallSession can transition from initiated to active."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    
    session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    # Act
    session.activate()
    
    # Assert
    assert session.state == "active"


def test_call_session_can_transition_to_ended() -> None:
    """Test that CallSession can transition to ended state."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    
    session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    # Act
    session.end()
    
    # Assert
    assert session.state == "ended"
    assert session.ended_at is not None


def test_call_session_records_timestamps() -> None:
    """Test that CallSession records start and end timestamps."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    
    before = datetime.now(timezone.utc)
    
    # Act
    session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    after = datetime.now(timezone.utc)
    
    # Assert
    assert before <= session.started_at <= after
    assert session.ended_at is None
    
    # End session
    before_end = datetime.now(timezone.utc)
    session.end()
    after_end = datetime.now(timezone.utc)
    
    assert session.ended_at is not None
    assert before_end <= session.ended_at <= after_end


def test_call_session_cannot_transition_from_ended() -> None:
    """Test that ended CallSession cannot transition to other states."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    
    session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    session.end()
    
    # Act & Assert
    with pytest.raises(ValueError, match="Cannot activate ended call"):
        session.activate()


def test_call_session_identity_based_on_stream_identifier() -> None:
    """Test that CallSession identity is based on stream_identifier."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    session1 = CallSession(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    session2 = CallSession(
        stream_identifier=stream_id,
        caller_number="+9999999999",  # Different number
        called_number="+1111111111",
        audio_format=audio_format
    )
    
    # Assert - Same stream_identifier means same identity
    assert session1 == session2


def test_call_session_supports_custom_parameters() -> None:
    """Test that CallSession can store custom routing parameters."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    
    custom_params = {"language": "en-US", "department": "sales"}
    
    # Act
    session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
        custom_parameters=custom_params
    )
    
    # Assert
    assert session.custom_parameters == custom_params
    assert session.custom_parameters["language"] == "en-US"


def test_call_session_duration() -> None:
    """Test that CallSession can calculate duration."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    import time
    
    session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    # Wait a bit
    time.sleep(0.1)
    
    # Act
    session.end()
    duration = session.duration_seconds
    
    # Assert
    assert duration is not None
    assert duration >= 0.1  # At least 100ms


def test_call_session_duration_none_when_not_ended() -> None:
    """Test that duration is None for ongoing calls."""
    # Arrange
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.call_session import CallSession
    
    session = CallSession(
        stream_identifier=StreamIdentifier("stream-123"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    # Assert
    assert session.duration_seconds is None
