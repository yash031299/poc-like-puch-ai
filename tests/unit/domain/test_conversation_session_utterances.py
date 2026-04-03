"""Tests for ConversationSession with Utterances."""

import pytest
from datetime import datetime, timezone


def test_conversation_session_can_add_utterance() -> None:
    """Test that utterances can be added to the conversation."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    utterance = Utterance(
        text="Hello there",
        confidence=0.95,
        is_final=True,
        timestamp=datetime.now(timezone.utc)
    )
    
    conversation.add_utterance(utterance)
    
    assert len(conversation.utterances) == 1
    assert conversation.utterances[0] == utterance


def test_conversation_session_stores_multiple_utterances() -> None:
    """Test that multiple utterances can be stored in conversation."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Add three utterances
    for i, text in enumerate(["Hello", "How are you?", "I need help"], start=1):
        utterance = Utterance(
            text=text,
            confidence=0.90 + (i * 0.01),
            is_final=True,
            timestamp=datetime.now(timezone.utc)
        )
        conversation.add_utterance(utterance)
    
    assert len(conversation.utterances) == 3
    assert conversation.utterances[0].text == "Hello"
    assert conversation.utterances[1].text == "How are you?"
    assert conversation.utterances[2].text == "I need help"


def test_conversation_session_can_add_partial_utterance() -> None:
    """Test that partial utterances can be added."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Add partial utterance
    partial = Utterance(
        text="What is",
        confidence=0.80,
        is_final=False,
        timestamp=datetime.now(timezone.utc)
    )
    
    conversation.add_utterance(partial)
    
    assert len(conversation.utterances) == 1
    assert conversation.utterances[0].is_partial is True


def test_conversation_session_can_get_latest_utterance() -> None:
    """Test retrieving the most recent utterance."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # No utterances yet
    assert conversation.latest_utterance is None
    
    # Add first utterance
    utterance1 = Utterance(
        text="Hello",
        confidence=0.95,
        is_final=True,
        timestamp=datetime.now(timezone.utc)
    )
    conversation.add_utterance(utterance1)
    
    assert conversation.latest_utterance == utterance1
    
    # Add second utterance
    utterance2 = Utterance(
        text="How are you?",
        confidence=0.92,
        is_final=True,
        timestamp=datetime.now(timezone.utc)
    )
    conversation.add_utterance(utterance2)
    
    # Latest should be the second one
    assert conversation.latest_utterance == utterance2


def test_conversation_session_can_get_final_utterances() -> None:
    """Test retrieving only final (completed) utterances."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Add mix of final and partial utterances
    final1 = Utterance(text="Hello", confidence=0.95, is_final=True, timestamp=datetime.now(timezone.utc))
    partial = Utterance(text="What is", confidence=0.80, is_final=False, timestamp=datetime.now(timezone.utc))
    final2 = Utterance(text="Thank you", confidence=0.93, is_final=True, timestamp=datetime.now(timezone.utc))
    
    conversation.add_utterance(final1)
    conversation.add_utterance(partial)
    conversation.add_utterance(final2)
    
    # Get only final utterances
    final_utterances = conversation.final_utterances
    
    assert len(final_utterances) == 2
    assert final1 in final_utterances
    assert final2 in final_utterances
    assert partial not in final_utterances
