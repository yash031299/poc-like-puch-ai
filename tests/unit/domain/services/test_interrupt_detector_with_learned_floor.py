"""Unit tests for InterruptDetector with learned noise floor (Phase 3D.2)."""

import pytest
import struct
from unittest.mock import Mock, MagicMock

from src.domain.services.interrupt_detector import InterruptDetector
from src.domain.aggregates.conversation_session import ConversationSession
from src.infrastructure.audio_analyzer import AudioAnalyzer


class TestInterruptDetectorWithLearnedFloor:
    """Tests for interrupt detection with adaptive learned noise floor."""

    def test_detect_interrupt_uses_learned_noise_floor(self) -> None:
        """Test that interrupt detector uses session's learned noise floor."""
        # Arrange
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Set a learned noise floor on the session
        session.set_noise_floor(-30.0)
        assert session.is_noise_floor_learned() is True
        
        session.set_speaking()
        
        # Create audio that would be above -30dB but below -40dB
        # Use moderate energy audio
        audio_chunk = struct.pack('<100h', *([2000] * 100))
        
        # Act
        result = detector.detect_interrupt(session, audio_chunk)
        
        # Assert - Should detect interrupt using learned floor
        assert result is True
        assert session.is_interrupted()

    def test_detect_interrupt_falls_back_to_default_without_learning(self) -> None:
        """Test that detector uses default floor when noise floor not learned."""
        # Arrange
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Session uses default noise floor (not learned)
        assert session.is_noise_floor_learned() is False
        assert session.get_noise_floor() == -40.0
        
        session.set_speaking()
        
        # Create silent audio (zeros) that's below -40dB
        audio_chunk = b'\x00\x00' * 100
        
        # Act
        result = detector.detect_interrupt(session, audio_chunk)
        
        # Assert - Should use default floor
        assert result is False

    def test_detect_interrupt_high_learned_floor_fewer_false_positives(self) -> None:
        """Test that high learned floor (loud environment) reduces false positives."""
        # Arrange - Simulate loud phone background environment
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-loud-bg",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Learn a high noise floor (loud environment)
        session.set_noise_floor(-25.0)
        
        session.set_speaking()
        
        # Create moderate-energy audio (office background noise)
        # ~1500 amplitude = ~-30dB, below the learned floor of -25dB
        moderate_audio = struct.pack('<100h', *([1500] * 100))
        
        # Act
        result = detector.detect_interrupt(session, moderate_audio)
        
        # Assert - Should NOT detect interrupt (background noise, not speech)
        # because learned floor is higher, filtering out background
        assert result is False

    def test_detect_interrupt_low_learned_floor_catches_quiet_speech(self) -> None:
        """Test that low learned floor (quiet environment) catches quiet speakers."""
        # Arrange - Simulate quiet environment
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-quiet-env",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Learn a low noise floor (quiet environment)
        session.set_noise_floor(-60.0)
        
        session.set_speaking()
        
        # Create low-energy audio (quiet speaker)
        # ~200 amplitude = ~-55dB, above the learned floor of -60dB
        quiet_speech = struct.pack('<100h', *([200] * 100))
        
        # Act
        result = detector.detect_interrupt(session, quiet_speech)
        
        # Assert - Should detect interrupt (quiet speech is above low floor)
        assert result is True
        assert session.is_interrupted()

    def test_detect_interrupt_preserves_analyzer_original_threshold(self) -> None:
        """Test that detector preserves analyzer's original threshold after check."""
        # Arrange
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-25.0)  # Learned floor different from analyzer's
        session.set_speaking()
        
        original_threshold = analyzer.get_noise_floor_db()
        audio_chunk = b'\x00\x01\x02\x03'
        
        # Act
        detector.detect_interrupt(session, audio_chunk)
        
        # Assert - Analyzer's threshold should be unchanged
        assert analyzer.get_noise_floor_db() == original_threshold


class TestInterruptDetectorLearnedFloorStateMachine:
    """Tests for state machine with learned floor."""

    def test_learned_floor_not_affected_by_state_changes(self) -> None:
        """Test that learned floor persists across state transitions."""
        # Arrange
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-28.0)
        learned_floor = session.get_noise_floor()
        
        # Act - Change states multiple times
        session.set_listening()
        session.set_thinking()
        session.set_speaking()
        
        # Assert - Learned floor should persist
        assert session.get_noise_floor() == learned_floor
        assert session.is_noise_floor_learned() is True

    def test_multiple_interrupts_use_learned_floor(self) -> None:
        """Test that multiple interrupt checks use the learned floor consistently."""
        # Arrange
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-30.0)
        
        # Create borderline audio (just above -30dB)
        borderline_audio = struct.pack('<100h', *([2500] * 100))
        
        # Act - First check
        session.set_speaking()
        result1 = detector.detect_interrupt(session, borderline_audio)
        
        # Reset interrupt flag
        session.reset_interrupt()
        session.set_speaking()
        
        # Second check with same audio
        result2 = detector.detect_interrupt(session, borderline_audio)
        
        # Assert - Both should give same result using learned floor
        assert result1 == result2

    def test_learned_floor_survives_reset_context(self) -> None:
        """Test that learned noise floor survives context reset."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-28.5)
        learned_floor_before = session.get_noise_floor()
        
        # Act - Reset context (simulating 'start over' event)
        session.reset_context()
        
        # Assert - Learned floor should survive reset
        assert session.get_noise_floor() == learned_floor_before
        assert session.is_noise_floor_learned() is True


class TestInterruptDetectorLearnedFloorEdgeCases:
    """Tests for edge cases with learned noise floor."""

    def test_detect_interrupt_with_extreme_learned_floor(self) -> None:
        """Test detector behavior with extreme learned floor values."""
        # Arrange
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Set very high learned floor (loud environment)
        session.set_noise_floor(-10.0)
        session.set_speaking()
        
        # Create very high energy audio
        loud_audio = struct.pack('<100h', *([20000] * 100))
        
        # Act
        result = detector.detect_interrupt(session, loud_audio)
        
        # Assert - Should still detect above high floor
        assert result is True

    def test_detect_interrupt_respects_negative_floor_constraint(self) -> None:
        """Test that learned floors are always <= 0dB."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Act & Assert - Setting positive floor should raise error
        with pytest.raises(ValueError, match="Noise floor must be <= 0dB"):
            session.set_noise_floor(5.0)

    def test_detect_interrupt_with_maximum_negative_floor(self) -> None:
        """Test detector with very low (maximum negative) learned floor."""
        # Arrange
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Set very low (sensitive) floor
        session.set_noise_floor(-80.0)
        session.set_speaking()
        
        # Create very quiet audio
        quiet_audio = struct.pack('<100h', *([50] * 100))
        
        # Act
        result = detector.detect_interrupt(session, quiet_audio)
        
        # Assert - Very quiet audio should still be detected above -80dB floor
        assert result is True

    def test_detect_interrupt_on_ended_session_ignores_floor(self) -> None:
        """Test that interrupt detection on ended session ignores learned floor."""
        # Arrange
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-25.0)
        session.set_speaking()
        session.end()
        
        audio_chunk = struct.pack('<100h', *([5000] * 100))
        
        # Act
        result = detector.detect_interrupt(session, audio_chunk)
        
        # Assert - Cannot interrupt ended session (regardless of floor)
        assert result is False


class TestInterruptDetectorLearnedFloorIntegration:
    """Integration tests combining learning and interrupt detection."""

    def test_interrupt_detector_with_mock_analyzer_respects_learned_floor(self) -> None:
        """Test interrupt detector correctly applies learned floor to analyzer."""
        # Arrange
        mock_analyzer = Mock()
        mock_analyzer.get_noise_floor_db.return_value = -40.0
        mock_analyzer.is_above_noise_floor.return_value = True
        
        detector = InterruptDetector(analyzer=mock_analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-25.0)
        session.set_speaking()
        
        audio_chunk = b'\x00\x01\x02\x03'
        
        # Act
        result = detector.detect_interrupt(session, audio_chunk)
        
        # Assert
        assert result is True
        # Verify analyzer's threshold was updated
        mock_analyzer.set_noise_floor_db.assert_called()

    def test_real_analyzer_with_learned_floor_detects_correctly(self) -> None:
        """Integration test with real analyzer and learned floor."""
        # Arrange
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-test",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Learn high floor from loud environment
        session.set_noise_floor(-20.0)
        session.set_speaking()
        
        # Create moderate energy audio (should be below -20dB threshold)
        moderate_audio = struct.pack('<100h', *([1000] * 100))
        
        # Act
        result = detector.detect_interrupt(session, moderate_audio)
        
        # Assert - Moderate audio below high threshold should not trigger
        assert result is False
