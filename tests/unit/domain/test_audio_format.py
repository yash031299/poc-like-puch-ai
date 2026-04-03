"""Unit tests for AudioFormat value object."""

import pytest


def test_audio_format_can_be_created_with_valid_parameters() -> None:
    """Test that AudioFormat can be created with sample rate, encoding, and channels."""
    # Arrange & Act
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(
        sample_rate=16000,
        encoding="PCM16LE",
        channels=1
    )
    
    # Assert
    assert audio_format.sample_rate == 16000
    assert audio_format.encoding == "PCM16LE"
    assert audio_format.channels == 1


def test_audio_format_validates_sample_rate() -> None:
    """Test that AudioFormat rejects invalid sample rates."""
    # Arrange
    from src.domain.value_objects.audio_format import AudioFormat
    
    # Act & Assert
    with pytest.raises(ValueError, match="Sample rate must be positive"):
        AudioFormat(sample_rate=0, encoding="PCM16LE", channels=1)
    
    with pytest.raises(ValueError, match="Sample rate must be positive"):
        AudioFormat(sample_rate=-1000, encoding="PCM16LE", channels=1)


def test_audio_format_validates_channels() -> None:
    """Test that AudioFormat only accepts 1 (mono) or 2 (stereo) channels."""
    # Arrange
    from src.domain.value_objects.audio_format import AudioFormat
    
    # Act & Assert - Valid
    mono = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    stereo = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=2)
    
    assert mono.channels == 1
    assert stereo.channels == 2
    
    # Invalid
    with pytest.raises(ValueError, match="Channels must be 1 \\(mono\\) or 2 \\(stereo\\)"):
        AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=0)
    
    with pytest.raises(ValueError, match="Channels must be 1 \\(mono\\) or 2 \\(stereo\\)"):
        AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=5)


def test_audio_format_validates_encoding() -> None:
    """Test that AudioFormat rejects empty encoding."""
    # Arrange
    from src.domain.value_objects.audio_format import AudioFormat
    
    # Act & Assert
    with pytest.raises(ValueError, match="Encoding cannot be empty"):
        AudioFormat(sample_rate=16000, encoding="", channels=1)


def test_audio_format_is_immutable() -> None:
    """Test that AudioFormat properties cannot be changed after creation."""
    # Arrange
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    # Act & Assert
    with pytest.raises(AttributeError):
        audio_format.sample_rate = 8000  # type: ignore
    
    with pytest.raises(AttributeError):
        audio_format.encoding = "MP3"  # type: ignore
    
    with pytest.raises(AttributeError):
        audio_format.channels = 2  # type: ignore


def test_audio_format_equality() -> None:
    """Test that two AudioFormats with same parameters are equal."""
    # Arrange
    from src.domain.value_objects.audio_format import AudioFormat
    
    format1 = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    format2 = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    format3 = AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)
    
    # Assert
    assert format1 == format2
    assert format1 != format3


def test_audio_format_supports_common_telephony_rates() -> None:
    """Test AudioFormat with common telephony sample rates."""
    # Arrange
    from src.domain.value_objects.audio_format import AudioFormat
    
    # Act - Common telephony sample rates
    pstn = AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)  # PSTN quality
    wideband = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)  # Wideband
    hd = AudioFormat(sample_rate=24000, encoding="PCM16LE", channels=1)  # HD voice
    
    # Assert
    assert pstn.sample_rate == 8000
    assert wideband.sample_rate == 16000
    assert hd.sample_rate == 24000


def test_audio_format_string_representation() -> None:
    """Test that AudioFormat has meaningful string representation."""
    # Arrange
    from src.domain.value_objects.audio_format import AudioFormat
    
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    # Assert
    assert "16000" in str(audio_format)
    assert "PCM16LE" in str(audio_format)
    assert "1" in str(audio_format) or "mono" in str(audio_format).lower()
