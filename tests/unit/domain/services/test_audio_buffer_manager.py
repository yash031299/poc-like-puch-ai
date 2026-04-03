"""Unit tests for AudioBufferManager."""

import time
from datetime import datetime, timezone

import pytest

from src.adapters.webrtc_vad_adapter import WebRTCVADAdapter
from src.domain.entities.audio_chunk import AudioChunk
from src.domain.services.audio_buffer_manager import AudioBufferManager, BufferState
from src.domain.value_objects.audio_format import AudioFormat
from src.ports.voice_activity_detector_port import VoiceActivity, VoiceActivityDetectorPort


class MockVAD(VoiceActivityDetectorPort):
    """Mock VAD for controlled testing."""

    def __init__(self):
        self.activity_sequence = []
        self.call_count = 0
        self.reset_calls = []

    def detect_speech(self, chunk: AudioChunk) -> VoiceActivity:
        if self.call_count < len(self.activity_sequence):
            result = self.activity_sequence[self.call_count]
            self.call_count += 1
            return result
        return VoiceActivity.SILENCE

    def set_sensitivity(self, level: int) -> None:
        pass

    def reset(self, stream_id: str) -> None:
        self.reset_calls.append(stream_id)

    def is_compatible_format(self, chunk: AudioChunk) -> bool:
        return True


def create_test_chunk(seq: int, duration_ms: int = 20, sample_rate: int = 16000) -> AudioChunk:
    """Helper to create test audio chunks."""
    audio_format = AudioFormat(sample_rate=sample_rate, encoding="PCM16LE", channels=1)
    # Calculate bytes needed for duration: (sample_rate * duration_ms / 1000) * 2 bytes per sample
    num_bytes = int((sample_rate * duration_ms / 1000) * 2)
    return AudioChunk(
        sequence_number=seq,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=b"\x00" * num_bytes
    )


class TestAudioBufferManagerInitialization:
    """Test AudioBufferManager initialization."""

    def test_initialization_with_defaults(self):
        """Test manager initializes with default parameters."""
        vad = MockVAD()
        manager = AudioBufferManager(vad)

        assert manager.silence_threshold_ms == 700
        assert manager.max_buffer_duration_seconds == 30.0

    def test_initialization_with_custom_params(self):
        """Test manager initializes with custom parameters."""
        vad = MockVAD()
        manager = AudioBufferManager(
            vad,
            silence_threshold_ms=500,
            max_buffer_duration_seconds=20.0
        )

        assert manager.silence_threshold_ms == 500
        assert manager.max_buffer_duration_seconds == 20.0

    def test_initialization_with_invalid_silence_threshold_raises(self):
        """Test initialization raises for invalid silence threshold."""
        vad = MockVAD()

        with pytest.raises(ValueError, match="Silence threshold must be"):
            AudioBufferManager(vad, silence_threshold_ms=50)

    def test_initialization_with_invalid_max_duration_raises(self):
        """Test initialization raises for invalid max duration."""
        vad = MockVAD()

        with pytest.raises(ValueError, match="Max buffer duration must be"):
            AudioBufferManager(vad, max_buffer_duration_seconds=0)


class TestAudioBufferManagerStateTransitions:
    """Test state machine transitions."""

    def test_idle_to_speaking_on_first_speech(self):
        """Test transition from IDLE to SPEAKING when speech detected."""
        vad = MockVAD()
        vad.activity_sequence = [VoiceActivity.SPEECH]
        manager = AudioBufferManager(vad, silence_threshold_ms=500)

        chunk = create_test_chunk(1)
        result = manager.add_chunk("stream-1", chunk)

        assert result is None  # No flush yet
        metrics = manager.get_metrics("stream-1")
        assert metrics["state"] == BufferState.SPEAKING.value
        assert metrics["buffer_size"] == 1
        assert metrics["chunks_buffered"] == 1

    def test_stays_idle_on_silence(self):
        """Test stays in IDLE when only silence detected."""
        vad = MockVAD()
        vad.activity_sequence = [VoiceActivity.SILENCE, VoiceActivity.SILENCE]
        manager = AudioBufferManager(vad)

        chunk1 = create_test_chunk(1)
        result1 = manager.add_chunk("stream-1", chunk1)
        
        chunk2 = create_test_chunk(2)
        result2 = manager.add_chunk("stream-1", chunk2)

        assert result1 is None
        assert result2 is None
        metrics = manager.get_metrics("stream-1")
        assert metrics["state"] == BufferState.IDLE.value
        assert metrics["buffer_size"] == 0  # Chunks discarded in IDLE

    def test_speaking_to_silence_detected(self):
        """Test transition from SPEAKING to SILENCE_DETECTED."""
        vad = MockVAD()
        vad.activity_sequence = [
            VoiceActivity.SPEECH,   # Start speaking
            VoiceActivity.SPEECH,   # Continue speaking
            VoiceActivity.SILENCE,  # Silence detected
        ]
        manager = AudioBufferManager(vad, silence_threshold_ms=500)

        manager.add_chunk("stream-1", create_test_chunk(1))
        manager.add_chunk("stream-1", create_test_chunk(2))
        manager.add_chunk("stream-1", create_test_chunk(3))

        metrics = manager.get_metrics("stream-1")
        assert metrics["state"] == BufferState.SILENCE_DETECTED.value
        assert metrics["buffer_size"] == 3

    def test_silence_detected_back_to_speaking(self):
        """Test transition from SILENCE_DETECTED back to SPEAKING."""
        vad = MockVAD()
        vad.activity_sequence = [
            VoiceActivity.SPEECH,   # Start speaking
            VoiceActivity.SILENCE,  # Brief pause
            VoiceActivity.SPEECH,   # Resume speaking
        ]
        manager = AudioBufferManager(vad, silence_threshold_ms=500)

        manager.add_chunk("stream-1", create_test_chunk(1))
        manager.add_chunk("stream-1", create_test_chunk(2))
        manager.add_chunk("stream-1", create_test_chunk(3))

        metrics = manager.get_metrics("stream-1")
        assert metrics["state"] == BufferState.SPEAKING.value
        assert metrics["buffer_size"] == 3  # All chunks buffered


class TestAudioBufferManagerFlushing:
    """Test buffer flushing logic."""

    def test_flush_on_silence_threshold(self):
        """Test buffer flushes when silence threshold reached."""
        vad = MockVAD()
        vad.activity_sequence = [
            VoiceActivity.SPEECH,   # Start speaking
            VoiceActivity.SPEECH,   # Continue
            VoiceActivity.SILENCE,  # Start silence
        ]
        manager = AudioBufferManager(vad, silence_threshold_ms=100)  # Short threshold for test

        manager.add_chunk("stream-1", create_test_chunk(1))
        manager.add_chunk("stream-1", create_test_chunk(2))
        manager.add_chunk("stream-1", create_test_chunk(3))

        # Wait for silence threshold
        time.sleep(0.15)  # 150ms > 100ms threshold

        # Next chunk should trigger flush
        vad.activity_sequence.append(VoiceActivity.SILENCE)
        result = manager.add_chunk("stream-1", create_test_chunk(4))

        assert result is not None
        assert len(result) == 4  # All 4 chunks flushed
        assert result[0].sequence_number == 1
        assert result[3].sequence_number == 4

        # Check state reset to IDLE
        metrics = manager.get_metrics("stream-1")
        assert metrics["state"] == BufferState.IDLE.value
        assert metrics["buffer_size"] == 0
        assert metrics["flushes_count"] == 1

    def test_explicit_flush(self):
        """Test explicit flush via flush() method."""
        vad = MockVAD()
        vad.activity_sequence = [VoiceActivity.SPEECH, VoiceActivity.SPEECH]
        manager = AudioBufferManager(vad)

        manager.add_chunk("stream-1", create_test_chunk(1))
        manager.add_chunk("stream-1", create_test_chunk(2))

        result = manager.flush("stream-1")

        assert result is not None
        assert len(result) == 2
        metrics = manager.get_metrics("stream-1")
        assert metrics["buffer_size"] == 0
        assert metrics["flushes_count"] == 1

    def test_flush_empty_buffer_returns_none(self):
        """Test flushing empty buffer returns None."""
        vad = MockVAD()
        manager = AudioBufferManager(vad)

        result = manager.flush("stream-1")
        assert result is None

    def test_flush_nonexistent_stream_returns_none(self):
        """Test flushing nonexistent stream returns None."""
        vad = MockVAD()
        manager = AudioBufferManager(vad)

        result = manager.flush("nonexistent")
        assert result is None

    def test_flush_on_max_buffer_duration(self):
        """Test buffer flushes when max duration exceeded."""
        vad = MockVAD()
        # Keep detecting speech
        vad.activity_sequence = [VoiceActivity.SPEECH] * 200
        manager = AudioBufferManager(vad, max_buffer_duration_seconds=0.1)  # 100ms max

        # Add first chunk to start buffer
        manager.add_chunk("stream-1", create_test_chunk(1))
        
        # Wait to exceed max duration
        time.sleep(0.15)  # 150ms > 100ms max

        # Next chunk should trigger overflow flush
        result = manager.add_chunk("stream-1", create_test_chunk(2))

        assert result is not None
        assert len(result) == 2
        metrics = manager.get_metrics("stream-1")
        assert metrics["state"] == BufferState.IDLE.value


class TestAudioBufferManagerReset:
    """Test reset functionality."""

    def test_reset_clears_stream_state(self):
        """Test reset clears all state for a stream."""
        vad = MockVAD()
        vad.activity_sequence = [VoiceActivity.SPEECH, VoiceActivity.SPEECH]
        manager = AudioBufferManager(vad)

        manager.add_chunk("stream-1", create_test_chunk(1))
        manager.add_chunk("stream-1", create_test_chunk(2))

        # Reset
        manager.reset("stream-1")

        # Verify state cleared
        metrics = manager.get_metrics("stream-1")
        assert metrics["state"] == BufferState.IDLE.value
        assert metrics["buffer_size"] == 0
        assert metrics["chunks_buffered"] == 0

        # Verify VAD reset called
        assert "stream-1" in vad.reset_calls

    def test_reset_nonexistent_stream_no_error(self):
        """Test resetting nonexistent stream doesn't raise error."""
        vad = MockVAD()
        manager = AudioBufferManager(vad)

        # Should not raise
        manager.reset("nonexistent")


class TestAudioBufferManagerMultipleStreams:
    """Test handling multiple concurrent streams."""

    def test_independent_stream_buffers(self):
        """Test streams maintain independent buffers."""
        vad = MockVAD()
        vad.activity_sequence = [VoiceActivity.SPEECH] * 10
        manager = AudioBufferManager(vad)

        manager.add_chunk("stream-1", create_test_chunk(1))
        manager.add_chunk("stream-1", create_test_chunk(2))
        manager.add_chunk("stream-2", create_test_chunk(1))

        metrics1 = manager.get_metrics("stream-1")
        metrics2 = manager.get_metrics("stream-2")

        assert metrics1["buffer_size"] == 2
        assert metrics2["buffer_size"] == 1

    def test_flush_one_stream_doesnt_affect_others(self):
        """Test flushing one stream doesn't affect others."""
        vad = MockVAD()
        vad.activity_sequence = [VoiceActivity.SPEECH] * 10
        manager = AudioBufferManager(vad)

        manager.add_chunk("stream-1", create_test_chunk(1))
        manager.add_chunk("stream-2", create_test_chunk(1))

        result = manager.flush("stream-1")

        assert result is not None
        assert len(result) == 1

        metrics2 = manager.get_metrics("stream-2")
        assert metrics2["buffer_size"] == 1  # Unchanged


class TestAudioBufferManagerMetrics:
    """Test metrics collection."""

    def test_metrics_track_chunks_buffered(self):
        """Test metrics track total chunks buffered."""
        vad = MockVAD()
        vad.activity_sequence = [VoiceActivity.SPEECH] * 10
        manager = AudioBufferManager(vad)

        for i in range(5):
            manager.add_chunk("stream-1", create_test_chunk(i))

        metrics = manager.get_metrics("stream-1")
        assert metrics["chunks_buffered"] == 5

    def test_metrics_track_flushes(self):
        """Test metrics track number of flushes."""
        vad = MockVAD()
        vad.activity_sequence = [VoiceActivity.SPEECH] * 10
        manager = AudioBufferManager(vad)

        manager.add_chunk("stream-1", create_test_chunk(1))
        manager.flush("stream-1")
        
        manager.add_chunk("stream-1", create_test_chunk(2))
        manager.flush("stream-1")

        metrics = manager.get_metrics("stream-1")
        assert metrics["flushes_count"] == 2
        assert metrics["chunks_flushed_total"] == 2
        assert metrics["audio_seconds_flushed_total"] > 0


class TestAudioBufferManagerIntegrationWithRealVAD:
    """Integration tests with real WebRTC VAD."""

    def test_real_vad_silence_detection(self):
        """Test with real WebRTC VAD detecting silence."""
        vad = WebRTCVADAdapter(sensitivity=2)
        manager = AudioBufferManager(vad, silence_threshold_ms=200)

        # Create silence chunks
        for i in range(3):
            chunk = create_test_chunk(i)
            result = manager.add_chunk("stream-1", chunk)

        # Should stay idle (silence not buffered)
        metrics = manager.get_metrics("stream-1")
        assert metrics["state"] == BufferState.IDLE.value
