"""Integration test for UC-001: Successfully accept a new incoming call.

This test verifies the first Gherkin scenario from
features/UC-001-accept-incoming-call.feature matches our implementation.

Scenario: Successfully accept a new incoming call
  Given a caller dials the AI agent's phone number
  When the telephony provider routes the call to our service
  Then the system creates a new ConversationSession
  And the ConversationSession has a unique StreamIdentifier
  And the CallSession is in "initiated" state
  And a CallInitiated event is published
  And the system is ready to receive audio from the caller
"""

import pytest


def test_uc001_successfully_accept_new_incoming_call() -> None:
    """
    Integration test for UC-001 first scenario.
    
    Tests that when a caller dials the AI agent's phone number and the
    telephony provider routes the call, the system correctly creates
    a ConversationSession with all required properties.
    """
    # Arrange - Given a caller dials the AI agent's phone number
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.aggregates.conversation_session import ConversationSession
    
    caller_number = "+1234567890"
    called_number = "+0987654321"  # AI agent's number
    stream_id = StreamIdentifier("stream-abc-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    # Act - When the telephony provider routes the call to our service
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number=caller_number,
        called_number=called_number,
        audio_format=audio_format
    )
    
    # Assert - Then the system creates a new ConversationSession
    assert conversation is not None
    assert isinstance(conversation, ConversationSession)
    
    # And the ConversationSession has a unique StreamIdentifier
    assert conversation.stream_identifier == stream_id
    assert conversation.stream_identifier.value == "stream-abc-123"
    
    # And the CallSession is in "initiated" state
    assert conversation.call_session.state == "initiated"
    assert not conversation.is_ended
    
    # And the system is ready to receive audio from the caller
    # (CallSession has audio_format configured)
    assert conversation.call_session.audio_format == audio_format
    assert conversation.call_session.audio_format.sample_rate == 16000
    assert conversation.call_session.audio_format.encoding == "PCM16LE"
    assert conversation.call_session.audio_format.channels == 1


def test_uc001_accept_call_with_caller_identification() -> None:
    """
    Integration test for UC-001 second scenario.
    
    Scenario: Accept call with caller identification
      Given a caller with phone number "+1234567890" dials the AI agent
      When the call is connected
      Then the ConversationSession records the caller number as "+1234567890"
      And the ConversationSession records the dialed number
      And the call start timestamp is recorded
    """
    # Arrange & Act
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.aggregates.conversation_session import ConversationSession
    from datetime import datetime, timezone
    
    before_call = datetime.now(timezone.utc)
    
    conversation = ConversationSession.create(
        stream_identifier=StreamIdentifier("stream-456"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    after_call = datetime.now(timezone.utc)
    
    # Assert - Then the ConversationSession records the caller number
    assert conversation.call_session.caller_number == "+1234567890"
    
    # And the ConversationSession records the dialed number
    assert conversation.call_session.called_number == "+0987654321"
    
    # And the call start timestamp is recorded
    assert conversation.call_session.started_at is not None
    assert before_call <= conversation.call_session.started_at <= after_call


def test_uc001_accept_call_with_custom_parameters() -> None:
    """
    Integration test for UC-001 third scenario.
    
    Scenario: Accept call with custom routing parameters
      Given a caller dials the AI agent with custom parameters
      When the call is connected
      Then the custom parameters are stored in the ConversationSession
      And the parameters are available for AI processing
    """
    # Arrange & Act
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.aggregates.conversation_session import ConversationSession
    
    custom_params = {
        "language": "en-US",
        "department": "sales",
        "priority": "high"
    }
    
    conversation = ConversationSession.create(
        stream_identifier=StreamIdentifier("stream-789"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
        custom_parameters=custom_params
    )
    
    # Assert - Then the custom parameters are stored in the ConversationSession
    assert conversation.call_session.custom_parameters == custom_params
    
    # And the parameters are available for AI processing
    assert conversation.call_session.custom_parameters["language"] == "en-US"
    assert conversation.call_session.custom_parameters["department"] == "sales"
    assert conversation.call_session.custom_parameters["priority"] == "high"


def test_uc001_concurrent_calls_are_independent() -> None:
    """
    Integration test for concurrent call handling.
    
    Scenario: Handle concurrent calls independently
      Given caller A is already connected
      When caller B initiates a new call
      Then the system creates a separate ConversationSession for caller B
      And caller A's session is unaffected
      And each session has a distinct StreamIdentifier
    """
    # Arrange & Act - Given caller A is already connected
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.aggregates.conversation_session import ConversationSession
    
    caller_a_session = ConversationSession.create(
        stream_identifier=StreamIdentifier("stream-caller-a"),
        caller_number="+1111111111",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    # Activate caller A's session
    caller_a_session.activate()
    assert caller_a_session.call_session.state == "active"
    
    # When caller B initiates a new call
    caller_b_session = ConversationSession.create(
        stream_identifier=StreamIdentifier("stream-caller-b"),
        caller_number="+2222222222",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    )
    
    # Assert - Then the system creates a separate ConversationSession for caller B
    assert caller_b_session is not None
    assert caller_b_session != caller_a_session
    
    # And caller A's session is unaffected
    assert caller_a_session.call_session.state == "active"
    assert caller_a_session.call_session.caller_number == "+1111111111"
    
    # And caller B's session is independent
    assert caller_b_session.call_session.state == "initiated"
    assert caller_b_session.call_session.caller_number == "+2222222222"
    
    # And each session has a distinct StreamIdentifier
    assert caller_a_session.stream_identifier != caller_b_session.stream_identifier
