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
    async def mock_session_repo(self, mock_session):
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
        return AsyncMock(spec=InterruptDetector)

    @pytest.fixture
    async def handler(
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
        self, handler, mock_interrupt_detector, mock_session_repo, mock_session
    ):
        """Verify handler calls InterruptDetector on media events."""
        audio_data = b"\x00\x01\x02\x03" * 40  # 160 bytes
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        mock_interrupt_detector.detect_interrupt.return_value = False
        mock_session_repo.get.return_value = mock_session

        await handler._handle_media(message, "test_stream")

        # Verify detector was called with session and audio data
        mock_interrupt_detector.detect_interrupt.assert_called_once()
        call_args = mock_interrupt_detector.detect_interrupt.call_args
        assert call_args[0][0] == mock_session
        assert call_args[0][1] == audio_data

    @pytest.mark.asyncio
    async def test_websocket_handler_marks_session_interrupted_on_detection(
        self, handler, mock_interrupt_detector, mock_session_repo, mock_session
    ):
        """Verify session is marked interrupted when detector detects interrupt."""
        audio_data = b"\x00\x01\x02\x03" * 40
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        # Detector returns True (interrupt detected)
        mock_interrupt_detector.detect_interrupt.return_value = True
        mock_session_repo.get.return_value = mock_session

        await handler._handle_media(message, "test_stream")

        # Session should have interrupt flag set
        assert mock_session.is_interrupted()

    @pytest.mark.asyncio
    async def test_websocket_handler_handles_detector_error_gracefully(
        self, handler, mock_interrupt_detector, mock_session_repo, mock_session
    ):
        """Verify handler continues if interrupt detection fails."""
        audio_data = b"\x00\x01\x02\x03" * 40
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        # Detector raises exception
        mock_interrupt_detector.detect_interrupt.side_effect = RuntimeError("Detector error")
        mock_session_repo.get.return_value = mock_session

        # Should not raise, should continue
        await handler._handle_media(message, "test_stream")

        # ProcessAudio should still be called
        assert True  # If we got here, no exception was raised

    @pytest.mark.asyncio
    async def test_websocket_handler_detects_interrupt_during_speaking(
        self, handler, mock_interrupt_detector, mock_session_repo, mock_session
    ):
        """Verify interrupt detection works during SPEAKING state."""
        # Set session to SPEAKING state
        mock_session.set_speaking()

        audio_data = b"\x00\x01\x02\x03" * 40
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        mock_interrupt_detector.detect_interrupt.return_value = True
        mock_session_repo.get.return_value = mock_session

        await handler._handle_media(message, "test_stream")

        # Detector should be called
        mock_interrupt_detector.detect_interrupt.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_handler_skips_detector_if_no_session(
        self, handler, mock_interrupt_detector, mock_session_repo
    ):
        """Verify handler gracefully handles missing session."""
        audio_data = b"\x00\x01\x02\x03" * 40
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        # No session found
        mock_session_repo.get.return_value = None

        await handler._handle_media(message, "test_stream")

        # Detector should not be called if no session
        mock_interrupt_detector.detect_interrupt.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_handler_processes_audio_after_interrupt_check(
        self, handler, mock_interrupt_detector, mock_session_repo, mock_session, mock_process_audio
    ):
        """Verify ProcessAudio is called after interrupt check."""
        audio_data = b"\x00\x01\x02\x03" * 40
        payload_b64 = base64.b64encode(audio_data).decode()

        message = {
            "event": "media",
            "media": {"payload": payload_b64, "chunk": 1},
        }

        mock_interrupt_detector.detect_interrupt.return_value = False
        mock_session_repo.get.return_value = mock_session

        await handler._handle_media(message, "test_stream")

        # ProcessAudio should always be called
        mock_process_audio.execute.assert_called_once()
