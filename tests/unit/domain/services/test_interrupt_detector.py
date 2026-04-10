"""Unit tests for InterruptDetector service."""

import pytest
from unittest.mock import Mock, MagicMock

from src.domain.services.interrupt_detector import InterruptDetector
from src.domain.aggregates.conversation_session import ConversationSession


class TestInterruptDetectorDetection:
    """Tests for interrupt detection logic."""

    def test_detect_interrupt_only_during_speaking_state(self) -> None:
        """Test that interrupt is only detected during SPEAKING state."""
        # Arrange
        analyzer = Mock()
        analyzer.is_above_noise_floor.return_value = True
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        audio_chunk = b'\x00\x01\x02\x03'
        
        # Act & Assert - Not in SPEAKING state
        session.set_listening()
        assert not detector.detect_interrupt(session, audio_chunk)
        
        session.set_thinking()
        assert not detector.detect_interrupt(session, audio_chunk)
        
        # Only during SPEAKING should detect
        session.set_speaking()
        assert detector.detect_interrupt(session, audio_chunk)

    def test_detect_interrupt_requires_above_noise_floor(self) -> None:
        """Test that interrupt requires audio energy above noise floor."""
        # Arrange
        analyzer = Mock()
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_speaking()
        audio_chunk = b'\x00\x01\x02\x03'
        
        # Act & Assert - Below noise floor (silence)
        analyzer.is_above_noise_floor.return_value = False
        assert not detector.detect_interrupt(session, audio_chunk)
        
        # Above noise floor (speech)
        analyzer.is_above_noise_floor.return_value = True
        assert detector.detect_interrupt(session, audio_chunk)

    def test_detect_interrupt_sets_flag_on_session(self) -> None:
        """Test that detecting interrupt marks session as interrupted."""
        # Arrange
        analyzer = Mock()
        analyzer.is_above_noise_floor.return_value = True
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_speaking()
        audio_chunk = b'\x00\x01\x02\x03'
        
        # Act
        result = detector.detect_interrupt(session, audio_chunk)
        
        # Assert
        assert result is True
        assert session.is_interrupted()
        assert session.interaction_state == "listening"

    def test_detect_interrupt_returns_false_for_already_interrupted(self) -> None:
        """Test that subsequent calls return False if already interrupted."""
        # Arrange
        analyzer = Mock()
        analyzer.is_above_noise_floor.return_value = True
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_speaking()
        audio_chunk = b'\x00\x01\x02\x03'
        
        # Act - First call
        first_result = detector.detect_interrupt(session, audio_chunk)
        
        # Set back to speaking (to bypass the state check for second call)
        session.set_speaking()
        
        # Second call should return False (already interrupted)
        second_result = detector.detect_interrupt(session, audio_chunk)
        
        # Assert
        assert first_result is True
        assert second_result is False

    def test_detect_interrupt_ignores_empty_audio(self) -> None:
        """Test that empty audio chunks don't trigger interrupt."""
        # Arrange
        analyzer = Mock()
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_speaking()
        
        # Act
        result = detector.detect_interrupt(session, b'')
        
        # Assert
        assert result is False
        assert not session.is_interrupted()
        analyzer.is_above_noise_floor.assert_not_called()


class TestInterruptDetectorEdgeCases:
    """Tests for edge cases and error handling."""

    def test_detect_interrupt_with_real_analyzer(self) -> None:
        """Test interrupt detection with real AudioAnalyzer."""
        # Arrange
        from src.infrastructure.audio_analyzer import AudioAnalyzer
        
        # Create real analyzer with high noise floor for testing
        analyzer = AudioAnalyzer(noise_floor_db=-30.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_speaking()
        
        # Create audio with significant energy (simulated speech)
        # PCM16LE: loud samples ~20000
        audio_chunk = b'\x20\x4e' * 100  # Repeated high-energy samples
        
        # Act
        result = detector.detect_interrupt(session, audio_chunk)
        
        # Assert - Should detect speech above noise floor
        assert result is True
        assert session.is_interrupted()

    def test_detect_interrupt_returns_zero_for_silence(self) -> None:
        """Test that silence chunks don't trigger interrupt."""
        # Arrange
        from src.infrastructure.audio_analyzer import AudioAnalyzer
        
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_speaking()
        
        # Create silent audio (zeros)
        audio_chunk = b'\x00\x00' * 100
        
        # Act
        result = detector.detect_interrupt(session, audio_chunk)
        
        # Assert
        assert result is False
        assert not session.is_interrupted()

    def test_get_noise_floor_db(self) -> None:
        """Test that noise floor threshold is accessible."""
        # Arrange
        detector = InterruptDetector(noise_floor_db=-45.0)
        
        # Act
        noise_floor = detector.get_noise_floor_db()
        
        # Assert
        assert noise_floor == -45.0

    def test_detect_interrupt_on_ended_session(self) -> None:
        """Test that interrupt cannot be marked on ended session."""
        # Arrange
        analyzer = Mock()
        analyzer.is_above_noise_floor.return_value = True
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_speaking()
        session.end()
        
        audio_chunk = b'\x00\x01\x02\x03'
        
        # Act
        result = detector.detect_interrupt(session, audio_chunk)
        
        # Assert - Cannot interrupt ended session
        assert result is False


class TestInterruptDetectorStateTransitions:
    """Tests for state transitions during interrupt."""

    def test_interrupt_transitions_speaking_to_listening(self) -> None:
        """Test that interrupt transitions state from SPEAKING to LISTENING."""
        # Arrange
        analyzer = Mock()
        analyzer.is_above_noise_floor.return_value = True
        detector = InterruptDetector(analyzer=analyzer)
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_thinking()
        session.set_speaking()
        assert session.interaction_state == "speaking"
        
        audio_chunk = b'\x00\x01\x02\x03'
        
        # Act
        detector.detect_interrupt(session, audio_chunk)
        
        # Assert
        assert session.interaction_state == "listening"
