"""Unit tests for SpeechSegment entity."""

import pytest
from datetime import datetime, timezone


def test_speech_segment_can_be_created() -> None:
    """Test SpeechSegment creation."""
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    seg = SpeechSegment(
        response_id="resp-1",
        position=0,
        audio_data=bytes(3200),
        audio_format=fmt,
        is_last=False,
        timestamp=datetime.now(timezone.utc),
    )

    assert seg.response_id == "resp-1"
    assert seg.position == 0
    assert seg.is_last is False
    assert seg.size_bytes == 3200


def test_speech_segment_validates_response_id() -> None:
    """Test that response_id cannot be empty."""
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    with pytest.raises(ValueError, match="response_id cannot be empty"):
        SpeechSegment(
            response_id="",
            position=0,
            audio_data=bytes(320),
            audio_format=fmt,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )


def test_speech_segment_validates_audio_data() -> None:
    """Test that audio_data cannot be empty."""
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    with pytest.raises(ValueError, match="Audio data cannot be empty"):
        SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=b"",
            audio_format=fmt,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )


def test_speech_segment_validates_position() -> None:
    """Test that position must be non-negative."""
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    with pytest.raises(ValueError, match="Position must be non-negative"):
        SpeechSegment(
            response_id="resp-1",
            position=-1,
            audio_data=bytes(320),
            audio_format=fmt,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )


def test_speech_segment_ordering() -> None:
    """Test segments can be ordered by position."""
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    ts = datetime.now(timezone.utc)
    seg0 = SpeechSegment("r", 0, bytes(320), fmt, False, ts)
    seg1 = SpeechSegment("r", 1, bytes(320), fmt, True, ts)

    assert seg0 < seg1
    assert seg1 > seg0
    assert seg0 <= seg0
    assert sorted([seg1, seg0]) == [seg0, seg1]


def test_speech_segment_last_flag() -> None:
    """Test is_last marks the final segment of a response."""
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    ts = datetime.now(timezone.utc)

    mid = SpeechSegment("r", 0, bytes(320), fmt, False, ts)
    last = SpeechSegment("r", 1, bytes(320), fmt, True, ts)

    assert mid.is_last is False
    assert last.is_last is True


def test_speech_segment_duration_calculation() -> None:
    """Test duration based on PCM16LE format (2 bytes/sample)."""
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    ts = datetime.now(timezone.utc)
    # 32000 bytes = 16000 samples = 1.0 second
    seg = SpeechSegment("r", 0, bytes(32000), fmt, True, ts)

    assert abs(seg.duration_seconds - 1.0) < 0.01


def test_speech_segment_repr() -> None:
    """Test __repr__ is informative."""
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    seg = SpeechSegment("resp-1", 2, bytes(3200), fmt, True, datetime.now(timezone.utc))

    s = repr(seg)
    assert "SpeechSegment" in s
    assert "pos=2" in s
    assert "last" in s
