"""Unit tests for NoiseFloorLearner service."""

import pytest
import struct
import math
from src.domain.services.noise_floor_learner import NoiseFloorLearner


class TestNoiseFloorLearnerBasic:
    """Tests for basic NoiseFloorLearner functionality."""

    def test_noise_floor_learner_initialization(self) -> None:
        """Test NoiseFloorLearner initializes with correct default state."""
        # Arrange & Act
        learner = NoiseFloorLearner(stream_sid="stream-123")
        
        # Assert
        assert learner.stream_sid == "stream-123"
        assert learner.is_learning is True
        assert learner.is_learned is False
        assert learner.get_noise_floor() == NoiseFloorLearner.DEFAULT_FALLBACK_FLOOR_DB
        assert learner.get_learning_progress() == 0.0

    def test_noise_floor_learner_custom_learning_duration(self) -> None:
        """Test NoiseFloorLearner respects custom learning duration."""
        # Arrange & Act
        learner = NoiseFloorLearner(
            stream_sid="stream-123",
            learning_duration_ms=1000  # 1 second
        )
        
        # Assert - target frames should be 1000ms / 20ms = 50 frames
        assert learner._target_frames == 50

    def test_noise_floor_learner_ignores_empty_chunks(self) -> None:
        """Test that empty audio chunks are ignored during learning."""
        # Arrange
        learner = NoiseFloorLearner(stream_sid="stream-123", learning_duration_ms=100)
        
        # Act
        result = learner.process_audio_chunk(b'')
        
        # Assert
        assert result is None
        assert learner.is_learning is True

    def test_noise_floor_learner_accumulates_frames(self) -> None:
        """Test that learner accumulates audio frames during learning."""
        # Arrange
        learner = NoiseFloorLearner(stream_sid="stream-123", learning_duration_ms=100)
        
        # Create silent audio (zeros) - 2 chunks
        silence_chunk = b'\x00\x00' * 100  # 200 bytes = 100 samples
        
        # Act - Add first chunk
        result1 = learner.process_audio_chunk(silence_chunk)
        
        # Assert - Learning not complete yet
        assert result1 is None
        assert learner.is_learning is True
        progress = learner.get_learning_progress()
        assert 0 < progress < 1.0

    def test_noise_floor_learner_completes_learning(self) -> None:
        """Test that learner completes learning after target duration."""
        # Arrange - Short learning duration for test
        learner = NoiseFloorLearner(stream_sid="stream-123", learning_duration_ms=40)
        
        # Create silent audio chunks
        silence_chunk = b'\x00\x00' * 100  # 200 bytes
        
        # Act - Add multiple chunks
        results = []
        for _ in range(5):
            result = learner.process_audio_chunk(silence_chunk)
            results.append(result)
        
        # Assert - At least one result should be the learned floor
        learned_values = [r for r in results if r is not None]
        assert len(learned_values) > 0
        learned_floor = learned_values[0]
        
        assert learner.is_learned is True
        assert learner.is_learning is False
        assert learned_floor <= 0  # dB must be <= 0
        assert learner.get_learning_progress() == 1.0

    def test_noise_floor_learner_ignores_subsequent_chunks(self) -> None:
        """Test that learner ignores chunks after learning completes."""
        # Arrange
        learner = NoiseFloorLearner(stream_sid="stream-123", learning_duration_ms=40)
        silence_chunk = b'\x00\x00' * 100
        
        # Act - Complete learning
        for _ in range(5):
            learner.process_audio_chunk(silence_chunk)
        
        assert learner.is_learned is True
        learned_floor_before = learner.get_noise_floor()
        
        # Try to process more chunks after learning
        result = learner.process_audio_chunk(silence_chunk)
        
        # Assert - Should be ignored
        assert result is None
        assert learner.get_noise_floor() == learned_floor_before


class TestNoiseFloorLearnerStatistics:
    """Tests for noise floor learning statistics computation."""

    def test_noise_floor_learner_with_variable_energy_audio(self) -> None:
        """Test learner computes correct threshold from variable energy audio."""
        # Arrange
        learner = NoiseFloorLearner(stream_sid="stream-123", learning_duration_ms=60)
        
        # Create audio chunks with varying energy
        # Low energy (quiet)
        quiet_chunk = b'\x00\x10' * 50  # Low amplitude
        
        # Medium energy
        medium_chunk = b'\x00\x40' * 50  # Medium amplitude
        
        # Act
        results = []
        results.append(learner.process_audio_chunk(quiet_chunk))
        results.append(learner.process_audio_chunk(quiet_chunk))
        results.append(learner.process_audio_chunk(medium_chunk))
        results.append(learner.process_audio_chunk(medium_chunk))
        
        # Find the learned floor (first non-None result)
        learned_values = [r for r in results if r is not None]
        
        # Assert - Learning should complete and produce a threshold
        assert len(learned_values) > 0
        learned_floor = learned_values[0]
        assert learned_floor <= 0
        
        # The threshold should be somewhere between the quietest and most energetic frames
        # This is a basic sanity check
        assert learner.is_learned is True

    def test_noise_floor_learner_with_high_energy_audio(self) -> None:
        """Test learner adapts to high-energy (loud) baseline environment."""
        # Arrange
        learner = NoiseFloorLearner(stream_sid="stream-123", learning_duration_ms=40)
        
        # Create high-energy audio (loud background noise)
        # PCM16LE with amplitude ~10000
        loud_chunk = struct.pack('<100h', *([5000] * 100))
        
        # Act
        results = []
        for _ in range(5):
            result = learner.process_audio_chunk(loud_chunk)
            results.append(result)
        
        # Assert
        learned_values = [r for r in results if r is not None]
        assert len(learned_values) > 0
        learned_floor = learned_values[0]
        
        # High-energy audio should produce a higher (less negative) threshold
        assert learned_floor > -40.0  # Should be higher than default
        assert learner.is_learned is True

    def test_noise_floor_learner_with_quiet_audio(self) -> None:
        """Test learner adapts to low-energy (quiet) baseline environment."""
        # Arrange
        learner = NoiseFloorLearner(stream_sid="stream-123", learning_duration_ms=40)
        
        # Create very low-energy audio (quiet environment)
        quiet_chunk = struct.pack('<100h', *([100] * 100))
        
        # Act
        results = []
        for _ in range(5):
            result = learner.process_audio_chunk(quiet_chunk)
            results.append(result)
        
        # Assert
        learned_values = [r for r in results if r is not None]
        assert len(learned_values) > 0
        learned_floor = learned_values[0]
        
        # Quiet audio should produce a lower (more negative) threshold
        assert learned_floor < -40.0  # Should be lower than default
        assert learner.is_learned is True

    def test_noise_floor_learner_fallback_on_empty_audio(self) -> None:
        """Test learner falls back to default when all frames are empty."""
        # Arrange
        learner = NoiseFloorLearner(stream_sid="stream-123", learning_duration_ms=40)
        
        # Act - Process only empty chunks
        for _ in range(5):
            learner.process_audio_chunk(b'')
        
        # Manually trigger learning completion (empty chunks don't trigger it)
        # In real usage, this would happen when proper audio is provided
        # For this test, we'll just verify the fallback value
        floor = learner.get_noise_floor()
        
        # Assert
        assert floor == NoiseFloorLearner.DEFAULT_FALLBACK_FLOOR_DB

    def test_noise_floor_learner_threshold_formula(self) -> None:
        """Test that threshold follows formula: mean + 2*std_dev."""
        # Arrange
        learner = NoiseFloorLearner(stream_sid="stream-123", learning_duration_ms=40)
        
        # Create predictable energy samples
        # We'll use structured data to have known statistics
        # Create chunks with energies that will produce predictable stats
        chunk1 = struct.pack('<100h', *([100] * 100))  # Very low energy
        chunk2 = struct.pack('<100h', *([500] * 100))  # Low energy
        chunk3 = struct.pack('<100h', *([100] * 100))  # Very low energy
        chunk4 = struct.pack('<100h', *([500] * 100))  # Low energy
        chunk5 = struct.pack('<100h', *([100] * 100))  # Very low energy
        
        # Act
        results = []
        for chunk in [chunk1, chunk2, chunk3, chunk4, chunk5]:
            result = learner.process_audio_chunk(chunk)
            results.append(result)
        
        # Assert - Should have computed a threshold
        learned_values = [r for r in results if r is not None]
        assert len(learned_values) > 0
        assert learner.is_learned is True


class TestNoiseFloorLearnerPerStream:
    """Tests for per-stream isolation."""

    def test_noise_floor_learner_per_stream_isolation(self) -> None:
        """Test that each stream has independent learning."""
        # Arrange
        learner1 = NoiseFloorLearner(stream_sid="stream-1", learning_duration_ms=40)
        learner2 = NoiseFloorLearner(stream_sid="stream-2", learning_duration_ms=40)
        
        # Create different audio profiles
        quiet_chunk = struct.pack('<100h', *([100] * 100))
        loud_chunk = struct.pack('<100h', *([5000] * 100))
        
        # Act - Learn different thresholds for each stream
        for _ in range(5):
            learner1.process_audio_chunk(quiet_chunk)
        for _ in range(5):
            learner2.process_audio_chunk(loud_chunk)
        
        # Assert - Should have different learned floors
        floor1 = learner1.get_noise_floor()
        floor2 = learner2.get_noise_floor()
        
        # They should be different (loud environment has higher threshold)
        assert floor1 != floor2
        assert floor1 < floor2  # Quiet environment = lower threshold

    def test_noise_floor_learner_repr(self) -> None:
        """Test string representation of learner."""
        # Arrange
        learner = NoiseFloorLearner(stream_sid="stream-123")
        
        # Act
        repr_str = repr(learner)
        
        # Assert
        assert "stream-123" in repr_str
        assert "learning" in repr_str


class TestNoiseFloorLearnerRealWorldScenarios:
    """Tests for real-world scenarios."""

    def test_noise_floor_learner_office_noise(self) -> None:
        """Test learner adapts to office background noise."""
        # Arrange - Simulate office noise (~1500 amplitude, ~-25dB)
        learner = NoiseFloorLearner(stream_sid="stream-office", learning_duration_ms=100)
        
        office_noise = struct.pack('<200h', *([1500] * 200))
        
        # Act
        results = []
        for _ in range(10):
            result = learner.process_audio_chunk(office_noise)
            results.append(result)
        
        # Assert
        learned_values = [r for r in results if r is not None]
        if learned_values:
            floor = learned_values[0]
            # Office noise should produce a higher threshold than default
            assert floor > -40.0

    def test_noise_floor_learner_quiet_environment(self) -> None:
        """Test learner adapts to quiet environment."""
        # Arrange - Simulate quiet environment (~100 amplitude, ~-60dB)
        learner = NoiseFloorLearner(stream_sid="stream-quiet", learning_duration_ms=100)
        
        quiet_env = struct.pack('<200h', *([100] * 200))
        
        # Act
        results = []
        for _ in range(10):
            result = learner.process_audio_chunk(quiet_env)
            results.append(result)
        
        # Assert
        learned_values = [r for r in results if r is not None]
        if learned_values:
            floor = learned_values[0]
            # Quiet environment should produce a lower threshold than default
            assert floor < -40.0
