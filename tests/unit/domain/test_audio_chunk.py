"""Unit tests for AudioChunk entity."""

import pytest
from datetime import datetime, timezone


def test_audio_chunk_can_be_created() -> None:
    """Test that an AudioChunk can be created with required attributes."""
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    timestamp = datetime.now(timezone.utc)
    audio_data = b"\x00\x01\x02\x03"  # Raw audio bytes
    
    chunk = AudioChunk(
        sequence_number=1,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=audio_data
    )
    
    assert chunk is not None
    assert chunk.sequence_number == 1
    assert chunk.timestamp == timestamp
    assert chunk.audio_format == audio_format
    assert chunk.audio_data == audio_data


def test_audio_chunk_validates_sequence_number() -> None:
    """Test that sequence numbers must be non-negative."""
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    timestamp = datetime.now(timezone.utc)
    
    # Negative sequence number should raise error
    with pytest.raises(ValueError, match="Sequence number must be non-negative"):
        AudioChunk(
            sequence_number=-1,
            timestamp=timestamp,
            audio_format=audio_format,
            audio_data=b"\x00"
        )


def test_audio_chunk_validates_audio_data() -> None:
    """Test that audio data cannot be empty."""
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    timestamp = datetime.now(timezone.utc)
    
    # Empty audio data should raise error
    with pytest.raises(ValueError, match="Audio data cannot be empty"):
        AudioChunk(
            sequence_number=1,
            timestamp=timestamp,
            audio_format=audio_format,
            audio_data=b""
        )


def test_audio_chunk_ordering() -> None:
    """Test that AudioChunks can be compared by sequence number for ordering."""
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    timestamp = datetime.now(timezone.utc)
    
    chunk1 = AudioChunk(
        sequence_number=1,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=b"\x00"
    )
    
    chunk2 = AudioChunk(
        sequence_number=2,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=b"\x00"
    )
    
    chunk3 = AudioChunk(
        sequence_number=3,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=b"\x00"
    )
    
    # Test comparison operators
    assert chunk1 < chunk2
    assert chunk2 < chunk3
    assert chunk3 > chunk1
    assert chunk1 <= chunk2
    assert chunk2 >= chunk1


def test_audio_chunk_size_calculation() -> None:
    """Test that AudioChunk can calculate its size in bytes."""
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    timestamp = datetime.now(timezone.utc)
    audio_data = b"\x00\x01\x02\x03\x04"  # 5 bytes
    
    chunk = AudioChunk(
        sequence_number=1,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=audio_data
    )
    
    assert chunk.size_bytes == 5


def test_audio_chunk_duration_calculation() -> None:
    """Test that AudioChunk can calculate its duration based on format."""
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat
    
    # PCM16LE: 2 bytes per sample
    # 16000 Hz sample rate
    # 1 channel
    # 32000 bytes = 16000 samples = 1 second
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    timestamp = datetime.now(timezone.utc)
    audio_data = bytes(32000)  # 1 second of audio
    
    chunk = AudioChunk(
        sequence_number=1,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=audio_data
    )
    
    # Duration should be approximately 1.0 seconds
    assert abs(chunk.duration_seconds - 1.0) < 0.01


def test_audio_chunk_equality() -> None:
    """Test that AudioChunks are equal if they have the same sequence number."""
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    timestamp1 = datetime.now(timezone.utc)
    timestamp2 = datetime.now(timezone.utc)
    
    chunk1 = AudioChunk(
        sequence_number=1,
        timestamp=timestamp1,
        audio_format=audio_format,
        audio_data=b"\x00\x01"
    )
    
    chunk2 = AudioChunk(
        sequence_number=1,
        timestamp=timestamp2,  # Different timestamp
        audio_format=audio_format,
        audio_data=b"\x99\x99"  # Different data
    )
    
    chunk3 = AudioChunk(
        sequence_number=2,
        timestamp=timestamp1,
        audio_format=audio_format,
        audio_data=b"\x00\x01"
    )
    
    # Chunks with same sequence number are equal (entity identity)
    assert chunk1 == chunk2
    
    # Chunks with different sequence numbers are not equal
    assert chunk1 != chunk3


def test_audio_chunk_hashable() -> None:
    """Test that AudioChunks can be used in sets and as dict keys."""
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    timestamp = datetime.now(timezone.utc)
    
    chunk1 = AudioChunk(
        sequence_number=1,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=b"\x00"
    )
    
    chunk2 = AudioChunk(
        sequence_number=2,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=b"\x00"
    )
    
    # Should be able to add to set
    chunk_set = {chunk1, chunk2}
    assert len(chunk_set) == 2
    
    # Should be able to use as dict key
    chunk_dict = {chunk1: "first", chunk2: "second"}
    assert chunk_dict[chunk1] == "first"


def test_audio_chunk_string_representation() -> None:
    """Test that AudioChunk has a useful string representation."""
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    timestamp = datetime.now(timezone.utc)
    audio_data = b"\x00\x01\x02\x03\x04"  # 5 bytes
    
    chunk = AudioChunk(
        sequence_number=42,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=audio_data
    )
    
    repr_str = repr(chunk)
    assert "AudioChunk" in repr_str
    assert "seq=42" in repr_str
    assert "5 bytes" in repr_str
