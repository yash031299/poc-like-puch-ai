"""Integration tests for UC-005: Handle Call Termination."""

from datetime import datetime, timezone


def _make_conversation(stream_id: str = "stream-end"):
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat

    return ConversationSession.create(
        stream_identifier=StreamIdentifier(stream_id),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
    )


def test_uc005_call_terminates_cleanly() -> None:
    """
    Scenario: Caller hangs up normally
      Given a call is active
      When the caller terminates the call
      Then the ConversationSession is marked as ended
      And the CallSession records an end timestamp
      And no further audio or utterances can be added
    """
    import pytest

    conv = _make_conversation()
    conv.activate()
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    conv.add_audio_chunk(AudioChunk(1, datetime.now(timezone.utc), fmt, bytes(3200)))

    # Terminate the call
    conv.end()

    assert conv.is_ended is True
    assert conv.call_session.state == "ended"
    assert conv.call_session.ended_at is not None


def test_uc005_ended_call_records_duration() -> None:
    """
    Scenario: Call duration is recorded on termination
      Given a call was started
      When the call is ended
      Then the duration is calculable from start and end timestamps
    """
    from time import sleep

    conv = _make_conversation("stream-dur")
    conv.activate()
    sleep(0.02)  # ensure measurable duration
    conv.end()

    assert conv.call_session.duration_seconds is not None
    assert conv.call_session.duration_seconds > 0


def test_uc005_cannot_add_chunks_after_end() -> None:
    """
    Scenario: No audio accepted after call ends
      Given a call is ended
      When new audio arrives (late packet)
      Then the system rejects it
    """
    import pytest
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat

    conv = _make_conversation("stream-late")
    conv.activate()
    conv.end()

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    with pytest.raises(ValueError, match="Cannot add audio to an ended conversation"):
        conv.add_audio_chunk(AudioChunk(1, datetime.now(timezone.utc), fmt, bytes(3200)))


def test_uc005_multiple_calls_independently_terminated() -> None:
    """
    Scenario: Two concurrent calls terminate independently
      Given two active calls
      When one call is terminated
      Then only that call is ended
      And the other call remains active
    """
    conv_a = _make_conversation("stream-a")
    conv_b = _make_conversation("stream-b")

    conv_a.activate()
    conv_b.activate()

    # Only terminate A
    conv_a.end()

    assert conv_a.is_ended is True
    assert conv_b.is_ended is False
    assert conv_b.call_session.state == "active"
