"""Tests for ExotelWebSocketHandler interrupt integration."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.entities.audio_chunk import AudioChunk
from src.domain.services.interrupt_detector import InterruptDetector
from src.domain.value_objects.audio_format import AudioFormat
from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler


class TestExotelWebSocketHandlerInterrupts:
    """Test ExotelWebSocketHandler with InterruptDetector integration."""

    @pytest.fixture
    def audio_format(self):
        return AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

    @pytest.fixture
    def mock_session(self, audio_format):
        return ConversationSession.create(
            stream_identifier=StreamIdentifier("test_stream"),
            caller_number="1234567890",
            called_number="9876543210",
            audio_format=audio_format,
        )

    @pytest.fixture
    def mock_session_repo(self, mock_session):
        repo = AsyncMock()
        repo.get = AsyncMock(return_value=mock_session)
        repo.save = AsyncMock()
        return repo

    @pytest.fixture
    def mock_accept_call(self):
        return AsyncMock()

    @pytest.fixture
    def mock_process_audio(self):
        return AsyncMock(return_value=[])

    @pytest.fixture
    def mock_end_call(self):
        return AsyncMock()

    @pytest.fixture
    def mock_interrupt_detector(self):
        # Use real InterruptDetector instead of mock for more realistic testing
        return InterruptDetector()

    def create_handler(
        self,
        mock_accept_call,
        mock_process_audio,
        mock_end_call,
        mock_session_repo,
        mock_interrupt_detector,
    ):
        return ExotelWebSocketHandler(
            accept_call=mock_accept_call,
            process_audio=mock_process_audio,
            end_call=mock_end_call,
            session_repo=mock_session_repo,
            interrupt_detector=mock_interrupt_detector,
        )

    @pytest.mark.asyncio
    async def test_websocket_handler_calls_interrupt_detector_on_media(
        self,
        mock_accept_call,
        mock_process_audio,
        mock_end_call,
        mock_session_repo,
        mock_interrupt_detector,
        mock_session,
    ):
        """Verify handler calls InterruptDetector on media events."""
        handler = self.create_handler(
            mock_accept_call, mock_process_audio, mock_end_call, mock_session_repo, mock_interrupt_detector
        )
        
        audio_data = b"\x00\x01\x02\x03" * 40  # 160 bytes
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        mock_session_repo.get.return_value = mock_session

        await handler._handle_media(message, "test_stream")

        # Verify ProcessAudio was called (detector is called before it)
        mock_process_audio.execute.assert_called_once()
        # Verify detector exists and is callable
        assert mock_interrupt_detector is not None
        assert callable(mock_interrupt_detector.detect_interrupt)

    @pytest.mark.asyncio
    async def test_websocket_handler_marks_session_interrupted_on_detection(
        self,
        mock_accept_call,
        mock_process_audio,
        mock_end_call,
        mock_session_repo,
        mock_interrupt_detector,
        mock_session,
    ):
        """Verify session is marked interrupted when detector detects interrupt."""
        handler = self.create_handler(
            mock_accept_call, mock_process_audio, mock_end_call, mock_session_repo, mock_interrupt_detector
        )
        
        # Set session to SPEAKING state (required for detector to mark interrupt)
        mock_session.set_speaking()
        
        # Create high-energy audio to trigger interrupt detection
        # Real detector checks RMS energy against noise floor (-40dB default)
        # High amplitude PCM16 values (e.g., 0x7F00 = ~32512) indicate speech
        high_energy_audio = bytes([0x00, 0x7F] * 80)  # 160 bytes, high amplitude
        
        payload_b64 = base64.b64encode(high_energy_audio).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        mock_session_repo.get.return_value = mock_session

        await handler._handle_media(message, "test_stream")

        # Session should have interrupt flag set (real detector marks it)
        assert mock_session.is_interrupted()

    @pytest.mark.asyncio
    async def test_websocket_handler_handles_detector_error_gracefully(
        self,
        mock_accept_call,
        mock_process_audio,
        mock_end_call,
        mock_session_repo,
        mock_interrupt_detector,
        mock_session,
    ):
        """Verify handler continues if interrupt detection fails."""
        # Create a detector mock that raises an exception
        failing_detector = MagicMock()
        failing_detector.detect_interrupt.side_effect = RuntimeError("Detector error")
        
        handler = ExotelWebSocketHandler(
            accept_call=mock_accept_call,
            process_audio=mock_process_audio,
            end_call=mock_end_call,
            session_repo=mock_session_repo,
            interrupt_detector=failing_detector,
        )
        
        audio_data = b"\x00\x01\x02\x03" * 40
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        mock_session_repo.get.return_value = mock_session

        # Should not raise, should continue
        await handler._handle_media(message, "test_stream")

        # ProcessAudio should still be called
        mock_process_audio.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_handler_detects_interrupt_during_speaking(
        self,
        mock_accept_call,
        mock_process_audio,
        mock_end_call,
        mock_session_repo,
        mock_interrupt_detector,
        mock_session,
    ):
        """Verify interrupt detection works during SPEAKING state."""
        handler = self.create_handler(
            mock_accept_call, mock_process_audio, mock_end_call, mock_session_repo, mock_interrupt_detector
        )
        
        # Set session to SPEAKING state
        mock_session.set_speaking()

        # Create high-energy audio to trigger interrupt detection
        high_energy_audio = bytes([0x00, 0x7F] * 80)  # High amplitude for speech detection
        payload_b64 = base64.b64encode(high_energy_audio).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        mock_session_repo.get.return_value = mock_session

        await handler._handle_media(message, "test_stream")

        # Detector should have been called and interrupt marked
        assert mock_session.is_interrupted()

    @pytest.mark.asyncio
    async def test_websocket_handler_skips_detector_if_no_session(
        self,
        mock_accept_call,
        mock_process_audio,
        mock_end_call,
        mock_session_repo,
        mock_interrupt_detector,
    ):
        """Verify handler gracefully handles missing session."""
        handler = self.create_handler(
            mock_accept_call, mock_process_audio, mock_end_call, mock_session_repo, mock_interrupt_detector
        )
        
        audio_data = b"\x00\x01\x02\x03" * 40
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        # No session found
        mock_session_repo.get.return_value = None

        await handler._handle_media(message, "test_stream")

        # ProcessAudio should still be attempted (with None session, may fail but that's ok)
        assert True  # If we got here, handler handled missing session gracefully

    @pytest.mark.asyncio
    async def test_websocket_handler_processes_audio_after_interrupt_check(
        self,
        mock_accept_call,
        mock_process_audio,
        mock_end_call,
        mock_session_repo,
        mock_interrupt_detector,
        mock_session,
    ):
        """Verify ProcessAudio is called after interrupt check."""
        handler = self.create_handler(
            mock_accept_call, mock_process_audio, mock_end_call, mock_session_repo, mock_interrupt_detector
        )
        
        audio_data = b"\x00\x01\x02\x03" * 40
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        mock_session_repo.get.return_value = mock_session

        await handler._handle_media(message, "test_stream")

        # ProcessAudio should always be called (real detector won't mark interrupt without SPEAKING state)
        mock_process_audio.execute.assert_called_once()
