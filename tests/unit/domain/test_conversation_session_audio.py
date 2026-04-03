"""Additional tests for ConversationSession with AudioChunks."""

import pytest
from datetime import datetime, timezone


def test_conversation_session_can_add_audio_chunk() -> None:
    """Test that audio chunks can be added to the conversation."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.audio_chunk import AudioChunk
    
    # Create conversation
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Add audio chunk
    chunk = AudioChunk(
        sequence_number=1,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=b"\x00\x01\x02\x03"
    )
    
    conversation.add_audio_chunk(chunk)
    
    # Verify chunk was added
    assert len(conversation.audio_chunks) == 1
    assert conversation.audio_chunks[0] == chunk


def test_conversation_session_adds_chunks_in_order() -> None:
    """Test that audio chunks are stored in sequence order."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.audio_chunk import AudioChunk
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Add chunks in order
    for i in range(1, 4):
        chunk = AudioChunk(
            sequence_number=i,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=bytes([i])
        )
        conversation.add_audio_chunk(chunk)
    
    # Verify chunks are in order
    assert len(conversation.audio_chunks) == 3
    assert conversation.audio_chunks[0].sequence_number == 1
    assert conversation.audio_chunks[1].sequence_number == 2
    assert conversation.audio_chunks[2].sequence_number == 3


def test_conversation_session_handles_out_of_order_chunks() -> None:
    """Test that out-of-order chunks are buffered and reordered."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.audio_chunk import AudioChunk
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Add chunk 1
    chunk1 = AudioChunk(
        sequence_number=1,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=b"\x01"
    )
    conversation.add_audio_chunk(chunk1)
    
    # Add chunk 3 (out of order - 2 is missing)
    chunk3 = AudioChunk(
        sequence_number=3,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=b"\x03"
    )
    conversation.add_audio_chunk(chunk3)
    
    # Chunk 3 should be buffered, not in main sequence yet
    assert len(conversation.audio_chunks) == 1  # Only chunk 1
    assert len(conversation.buffered_chunks) == 1  # Chunk 3 buffered
    
    # Add chunk 2 (fills the gap)
    chunk2 = AudioChunk(
        sequence_number=2,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=b"\x02"
    )
    conversation.add_audio_chunk(chunk2)
    
    # Now all chunks should be in order
    assert len(conversation.audio_chunks) == 3
    assert len(conversation.buffered_chunks) == 0
    assert conversation.audio_chunks[0].sequence_number == 1
    assert conversation.audio_chunks[1].sequence_number == 2
    assert conversation.audio_chunks[2].sequence_number == 3


def test_conversation_session_rejects_duplicate_chunks() -> None:
    """Test that duplicate sequence numbers are rejected."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.audio_chunk import AudioChunk
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Add chunk 1
    chunk1 = AudioChunk(
        sequence_number=1,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=b"\x01"
    )
    conversation.add_audio_chunk(chunk1)
    
    # Try to add another chunk with sequence 1
    duplicate = AudioChunk(
        sequence_number=1,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=b"\xFF"  # Different data
    )
    
    with pytest.raises(ValueError, match="Audio chunk with sequence 1 already exists"):
        conversation.add_audio_chunk(duplicate)


def test_conversation_session_validates_audio_format_match() -> None:
    """Test that added chunks must match the call's audio format."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.audio_chunk import AudioChunk
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Try to add chunk with mismatched format
    wrong_format = AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)
    chunk = AudioChunk(
        sequence_number=1,
        timestamp=datetime.now(timezone.utc),
        audio_format=wrong_format,
        audio_data=b"\x00"
    )
    
    with pytest.raises(ValueError, match="Audio format mismatch"):
        conversation.add_audio_chunk(chunk)


def test_conversation_session_can_retrieve_chunks_by_sequence() -> None:
    """Test that chunks can be retrieved by sequence number."""
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.audio_chunk import AudioChunk
    
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    
    # Add some chunks
    for i in range(1, 4):
        chunk = AudioChunk(
            sequence_number=i,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=bytes([i])
        )
        conversation.add_audio_chunk(chunk)
    
    # Retrieve specific chunk
    chunk2 = conversation.get_audio_chunk(2)
    assert chunk2 is not None
    assert chunk2.sequence_number == 2
    
    # Try to get non-existent chunk
    chunk99 = conversation.get_audio_chunk(99)
    assert chunk99 is None
