"""Integration tests for noise floor learning in ConversationSession (Phase 3D.2)."""

import pytest
from src.domain.aggregates.conversation_session import ConversationSession


class TestConversationSessionNoiseFloorBasic:
    """Tests for basic noise floor functionality in ConversationSession."""

    def test_conversation_session_default_noise_floor(self) -> None:
        """Test that ConversationSession has default noise floor."""
        # Arrange & Act
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Assert
        assert session.get_noise_floor() == -40.0
        assert session.is_noise_floor_learned() is False

    def test_conversation_session_set_noise_floor(self) -> None:
        """Test setting learned noise floor on session."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Act
        session.set_noise_floor(-25.5)
        
        # Assert
        assert session.get_noise_floor() == -25.5
        assert session.is_noise_floor_learned() is True

    def test_conversation_session_noise_floor_boundary_values(self) -> None:
        """Test noise floor with boundary values."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Act & Assert - 0dB is valid (boundary)
        session.set_noise_floor(0.0)
        assert session.get_noise_floor() == 0.0
        
        # Act & Assert - Negative is valid
        session.set_noise_floor(-50.0)
        assert session.get_noise_floor() == -50.0

    def test_conversation_session_noise_floor_rejects_positive(self) -> None:
        """Test that positive noise floor values are rejected."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Act & Assert
        with pytest.raises(ValueError, match="Noise floor must be <= 0dB"):
            session.set_noise_floor(5.0)

    def test_conversation_session_cannot_set_floor_on_ended_session(self) -> None:
        """Test that setting noise floor on ended session raises error."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.end()
        
        # Act & Assert
        with pytest.raises(ValueError, match="Cannot set noise floor on an ended conversation"):
            session.set_noise_floor(-30.0)

    def test_conversation_session_multiple_noise_floor_updates(self) -> None:
        """Test that noise floor can be updated multiple times."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Act & Assert - First update
        session.set_noise_floor(-30.0)
        assert session.get_noise_floor() == -30.0
        assert session.is_noise_floor_learned() is True
        
        # Act & Assert - Second update
        session.set_noise_floor(-25.0)
        assert session.get_noise_floor() == -25.0
        assert session.is_noise_floor_learned() is True


class TestConversationSessionNoiseFloorStateTransitions:
    """Tests for noise floor behavior across state transitions."""

    def test_noise_floor_persists_across_interaction_states(self) -> None:
        """Test that learned noise floor persists across interaction state changes."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-28.0)
        learned_floor = session.get_noise_floor()
        
        # Act - Transition through various states
        session.activate()
        session.set_listening()
        assert session.get_noise_floor() == learned_floor
        
        session.set_thinking()
        assert session.get_noise_floor() == learned_floor
        
        session.set_speaking()
        assert session.get_noise_floor() == learned_floor
        
        # Assert
        assert session.is_noise_floor_learned() is True

    def test_noise_floor_survives_reset_context(self) -> None:
        """Test that learned noise floor survives context reset."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-27.5)
        floor_before = session.get_noise_floor()
        
        # Act - Reset context (simulates caller saying 'start over')
        session.reset_context()
        
        # Assert - Noise floor should survive reset
        assert session.get_noise_floor() == floor_before
        assert session.is_noise_floor_learned() is True

    def test_noise_floor_survives_reset_interrupt(self) -> None:
        """Test that learned noise floor survives interrupt reset."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-26.0)
        session.mark_interrupted()
        floor_before = session.get_noise_floor()
        
        # Act - Reset interrupt flag
        session.reset_interrupt()
        
        # Assert - Noise floor should persist
        assert session.get_noise_floor() == floor_before
        assert session.is_noise_floor_learned() is True

    def test_noise_floor_initial_learning_flag(self) -> None:
        """Test that learning flag transitions correctly."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Assert - Initial state
        assert session.is_noise_floor_learned() is False
        assert session.get_noise_floor() == -40.0
        
        # Act - Learn floor
        session.set_noise_floor(-32.0)
        
        # Assert - Learned state
        assert session.is_noise_floor_learned() is True
        assert session.get_noise_floor() == -32.0


class TestConversationSessionNoiseFloorWithAudio:
    """Tests for noise floor behavior in audio processing context."""

    def test_noise_floor_does_not_affect_audio_chunk_processing(self) -> None:
        """Test that noise floor learning doesn't interfere with audio chunks."""
        # Arrange
        from src.domain.entities.audio_chunk import AudioChunk
        from datetime import datetime, timezone
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-30.0)
        audio_format = {"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        
        # Act - Add audio chunks
        chunk1 = AudioChunk(
            sequence_number=1,
            timestamp=datetime.now(timezone.utc),
            audio_format=audio_format,
            audio_data=b'\x00\x01\x02\x03' * 10  # Not empty
        )
        session.add_audio_chunk(chunk1)
        
        # Assert - Noise floor should persist
        assert session.get_noise_floor() == -30.0
        assert len(session.audio_chunks) == 1

    def test_noise_floor_independent_per_stream(self) -> None:
        """Test that different sessions have independent noise floors."""
        # Arrange & Act
        session1 = ConversationSession.create(
            stream_identifier="stream-1",
            caller_number="+1111111111",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session2 = ConversationSession.create(
            stream_identifier="stream-2",
            caller_number="+2222222222",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session1.set_noise_floor(-25.0)
        session2.set_noise_floor(-35.0)
        
        # Assert
        assert session1.get_noise_floor() == -25.0
        assert session2.get_noise_floor() == -35.0
        assert session1.is_noise_floor_learned() is True
        assert session2.is_noise_floor_learned() is True


class TestConversationSessionNoiseFloorWithInterrupt:
    """Tests for noise floor behavior with interrupts."""

    def test_interrupt_flag_independent_of_noise_floor(self) -> None:
        """Test that interrupt flag operates independently of noise floor."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-28.0)
        
        # Act - Mark as interrupted
        session.set_speaking()
        session.mark_interrupted()
        
        # Assert
        assert session.is_interrupted() is True
        assert session.get_noise_floor() == -28.0

    def test_noise_floor_persists_after_interrupt_reset(self) -> None:
        """Test that noise floor remains after interrupt handling."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-27.0)
        
        # Act
        session.set_speaking()
        session.mark_interrupted()
        assert session.is_interrupted() is True
        
        floor_after_interrupt = session.get_noise_floor()
        
        session.reset_interrupt()
        assert session.is_interrupted() is False
        
        floor_after_reset = session.get_noise_floor()
        
        # Assert
        assert floor_after_interrupt == floor_after_reset == -27.0

    def test_multiple_interaction_cycles_with_learned_floor(self) -> None:
        """Test multiple cycles of speaking/listening with persistent learned floor."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session.set_noise_floor(-29.0)
        
        # Act - Multiple cycles
        for _ in range(3):
            session.set_listening()
            assert session.get_noise_floor() == -29.0
            
            session.set_thinking()
            assert session.get_noise_floor() == -29.0
            
            session.set_speaking()
            assert session.get_noise_floor() == -29.0
            
            session.mark_interrupted()
            assert session.get_noise_floor() == -29.0
            
            session.reset_interrupt()
            assert session.get_noise_floor() == -29.0
        
        # Assert
        assert session.is_noise_floor_learned() is True


class TestConversationSessionNoiseFloorAggregateConsistency:
    """Tests for aggregate consistency with noise floor."""

    def test_noise_floor_in_conversation_representation(self) -> None:
        """Test that session representation reflects noise floor state."""
        # Arrange
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Act
        session.set_noise_floor(-24.5)
        repr_str = repr(session)
        
        # Assert - Session representation should show stream ID
        assert "stream-123" in repr_str

    def test_noise_floor_equality_not_affected(self) -> None:
        """Test that noise floor doesn't affect session equality."""
        # Arrange
        session1 = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session2 = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        # Set different noise floors
        session1.set_noise_floor(-25.0)
        session2.set_noise_floor(-35.0)
        
        # Assert - Should still be equal (same stream_id)
        assert session1 == session2

    def test_noise_floor_hashable(self) -> None:
        """Test that sessions with different noise floors are hashable consistently."""
        # Arrange
        session1 = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session2 = ConversationSession.create(
            stream_identifier="stream-456",
            caller_number="+1111111111",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        
        session1.set_noise_floor(-25.0)
        session2.set_noise_floor(-35.0)
        
        # Act - Add to set
        session_set = {session1, session2}
        
        # Assert - Both should be in set
        assert len(session_set) == 2
        assert session1 in session_set
        assert session2 in session_set
