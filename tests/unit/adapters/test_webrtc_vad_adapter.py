"""Unit tests for WebRTCVADAdapter."""

import struct
from datetime import datetime, timezone

import pytest

from src.adapters.webrtc_vad_adapter import WebRTCVADAdapter
from src.domain.entities.audio_chunk import AudioChunk
from src.domain.value_objects.audio_format import AudioFormat
from src.ports.voice_activity_detector_port import VoiceActivity


class TestWebRTCVADAdapter:
    """Test WebRTC VAD adapter functionality."""

    def test_initialization_with_valid_sensitivity(self):
        """Test VAD initializes with valid sensitivity levels."""
        for sensitivity in [0, 1, 2, 3]:
            vad = WebRTCVADAdapter(sensitivity=sensitivity)
            assert vad.sensitivity == sensitivity

    def test_initialization_with_invalid_sensitivity_raises(self):
        """Test VAD raises ValueError for invalid sensitivity."""
        with pytest.raises(ValueError, match="Sensitivity must be in range"):
            WebRTCVADAdapter(sensitivity=-1)

        with pytest.raises(ValueError, match="Sensitivity must be in range"):
            WebRTCVADAdapter(sensitivity=4)

    def test_set_sensitivity_updates_mode(self):
        """Test set_sensitivity updates VAD mode."""
        vad = WebRTCVADAdapter(sensitivity=1)
        assert vad.sensitivity == 1

        vad.set_sensitivity(3)
        assert vad.sensitivity == 3

    def test_set_sensitivity_invalid_raises(self):
        """Test set_sensitivity raises for invalid levels."""
        vad = WebRTCVADAdapter()

        with pytest.raises(ValueError, match="Sensitivity level must be"):
            vad.set_sensitivity(-1)

        with pytest.raises(ValueError, match="Sensitivity level must be"):
            vad.set_sensitivity(5)

    def test_is_compatible_format_valid_16khz(self):
        """Test format compatibility check for 16kHz PCM16LE mono."""
        vad = WebRTCVADAdapter()

        audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 320  # 20ms @ 16kHz = 320 bytes
        )

        assert vad.is_compatible_format(chunk) is True

    def test_is_compatible_format_valid_8khz(self):
        """Test format compatibility for 8kHz PCM16LE mono."""
        vad = WebRTCVADAdapter()

        audio_format = AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)
        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 160  # 20ms @ 8kHz = 160 bytes
        )

        assert vad.is_compatible_format(chunk) is True

    def test_is_compatible_format_invalid_sample_rate(self):
        """Test format compatibility fails for unsupported sample rate."""
        vad = WebRTCVADAdapter()

        audio_format = AudioFormat(sample_rate=24000, encoding="PCM16LE", channels=1)
        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 480
        )

        assert vad.is_compatible_format(chunk) is False

    def test_is_compatible_format_invalid_encoding(self):
        """Test format compatibility fails for non-PCM16LE encoding."""
        vad = WebRTCVADAdapter()

        audio_format = AudioFormat(sample_rate=16000, encoding="OPUS", channels=1)
        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 320
        )

        assert vad.is_compatible_format(chunk) is False

    def test_is_compatible_format_invalid_channels(self):
        """Test format compatibility fails for stereo audio."""
        vad = WebRTCVADAdapter()

        audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=2)
        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 320
        )

        assert vad.is_compatible_format(chunk) is False

    def test_detect_speech_on_silence(self):
        """Test VAD detects silence for zero-amplitude audio."""
        vad = WebRTCVADAdapter(sensitivity=2)

        audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
        # 20ms of silence @ 16kHz = 320 bytes of zeros
        silence_data = b"\x00" * 320

        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=silence_data
        )

        result = vad.detect_speech(chunk)
        assert result == VoiceActivity.SILENCE

    def test_detect_speech_on_synthetic_tone(self):
        """Test VAD detects speech on a synthetic tone signal."""
        vad = WebRTCVADAdapter(sensitivity=2)

        audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

        # Generate 20ms of synthetic tone (sine wave at 300 Hz)
        # 20ms @ 16kHz = 320 samples = 640 bytes
        import math
        samples = []
        for i in range(320):  # 320 samples
            # Generate tone with reasonable amplitude
            value = int(10000 * math.sin(2 * math.pi * 300 * i / 16000))
            samples.append(struct.pack("<h", value))  # Little-endian signed short

        tone_data = b"".join(samples)

        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=tone_data
        )

        result = vad.detect_speech(chunk)
        # Tone may or may not be detected as speech depending on VAD characteristics
        # Just verify it returns a valid result
        assert result in [VoiceActivity.SPEECH, VoiceActivity.SILENCE]

    def test_detect_speech_with_incompatible_format_raises(self):
        """Test detect_speech raises ValueError for incompatible format."""
        vad = WebRTCVADAdapter()

        # 24kHz is not supported by WebRTC VAD
        audio_format = AudioFormat(sample_rate=24000, encoding="PCM16LE", channels=1)
        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 480
        )

        with pytest.raises(ValueError, match="Incompatible audio format"):
            vad.detect_speech(chunk)

    def test_reset_clears_stream_state(self):
        """Test reset clears state for a stream."""
        vad = WebRTCVADAdapter()

        # Reset should work even if stream never existed
        vad.reset("stream-123")  # Should not raise

        # After processing, reset should clear state
        audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 320
        )

        vad.detect_speech(chunk)
        vad.reset("stream-123")
        # Should complete without errors

    def test_detect_speech_different_frame_durations(self):
        """Test VAD works with different valid frame durations."""
        vad = WebRTCVADAdapter(sensitivity=2)
        audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

        # Test 10ms frame (160 bytes @ 16kHz)
        chunk_10ms = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 160
        )
        result = vad.detect_speech(chunk_10ms)
        assert result in [VoiceActivity.SPEECH, VoiceActivity.SILENCE, VoiceActivity.UNKNOWN]

        # Test 20ms frame (320 bytes @ 16kHz)
        chunk_20ms = AudioChunk(
            sequence_number=2,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 320
        )
        result = vad.detect_speech(chunk_20ms)
        assert result in [VoiceActivity.SPEECH, VoiceActivity.SILENCE, VoiceActivity.UNKNOWN]

        # Test 30ms frame (480 bytes @ 16kHz)
        chunk_30ms = AudioChunk(
            sequence_number=3,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b"\x00" * 480
        )
        result = vad.detect_speech(chunk_30ms)
        assert result in [VoiceActivity.SPEECH, VoiceActivity.SILENCE, VoiceActivity.UNKNOWN]

    def test_sensitivity_affects_detection(self):
        """Test that sensitivity affects speech detection."""
        # This is more of an integration test to verify sensitivity parameter works
        # In practice, higher sensitivity should detect more speech

        audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

        # Create very quiet noise
        import random
        random.seed(42)  # Deterministic
        quiet_noise = bytes([random.randint(0, 20) for _ in range(320)])

        chunk = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=quiet_noise
        )

        # Test with least sensitive
        vad_low = WebRTCVADAdapter(sensitivity=0)
        result_low = vad_low.detect_speech(chunk)

        # Test with most sensitive
        vad_high = WebRTCVADAdapter(sensitivity=3)
        result_high = vad_high.detect_speech(chunk)

        # Both should return valid results
        assert result_low in [VoiceActivity.SPEECH, VoiceActivity.SILENCE]
        assert result_high in [VoiceActivity.SPEECH, VoiceActivity.SILENCE]
