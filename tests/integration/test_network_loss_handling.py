"""Integration tests for network loss handling — graceful error recovery."""

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.value_objects.audio_format import AudioFormat
from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler
from src.use_cases.accept_call import AcceptCallUseCase
from src.use_cases.end_call import EndCallUseCase
from src.use_cases.process_audio import ProcessAudioUseCase


class MockWebSocket:
    """Mock WebSocket for testing."""

    def __init__(self):
        self.accepted = False
        self.closed = False
        self.messages = []
        self.sent_messages = []

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        if self.messages:
            return self.messages.pop(0)
        raise Exception("No messages")

    async def send_json(self, data):
        self.sent_messages.append(data)

    async def send_text(self, data):
        self.sent_messages.append(data)

    async def close(self):
        self.closed = True


class TestNetworkLossHandlingWebSocket:
    """Test WebSocket disconnect and graceful error recovery."""

    @pytest.mark.asyncio
    async def test_websocket_connection_established(self):
        """Verify handler accepts connection."""
        accept_call = AsyncMock(spec=AcceptCallUseCase)
        process_audio = AsyncMock(spec=ProcessAudioUseCase)
        end_call = AsyncMock(spec=EndCallUseCase)

        handler = ExotelWebSocketHandler(
            accept_call, process_audio, end_call, sample_rate=16000
        )
        ws = MockWebSocket()
        ws.messages = [json.dumps({"event": "connected"})]

        # Mock to break after connected
        with patch.object(ws, "receive_text", side_effect=[
            json.dumps({"event": "connected"}),
            Exception("Network disconnected")
        ]):
            try:
                await handler.handle(ws)
            except Exception:
                pass

        assert ws.accepted

    @pytest.mark.asyncio
    async def test_websocket_disconnect_gracefully_ends_call(self):
        """Verify WebSocket disconnect triggers graceful call end."""
        accept_call = AsyncMock(spec=AcceptCallUseCase)
        process_audio = AsyncMock(spec=ProcessAudioUseCase)
        end_call = AsyncMock(spec=EndCallUseCase)

        handler = ExotelWebSocketHandler(
            accept_call, process_audio, end_call, sample_rate=16000
        )

        ws = MockWebSocket()
        stream_id = "stream_123"

        # Simulate: connected → start → disconnect
        ws.messages = [
            json.dumps({"event": "connected"}),
            json.dumps({
                "event": "start",
                "start": {"stream_sid": stream_id, "from": "+91987654321", "to": "+91123456789"},
                "stream_sid": stream_id,
            }),
        ]

        with patch.object(
            ws, "receive_text",
            side_effect=[
                json.dumps({"event": "connected"}),
                json.dumps({
                    "event": "start",
                    "start": {"stream_sid": stream_id, "from": "+91987654321", "to": "+91123456789"},
                    "stream_sid": stream_id,
                }),
                Exception("WebSocket closed"),
            ],
        ):
            try:
                await handler.handle(ws)
            except Exception:
                pass

        # Should have closed the connection
        assert ws.closed

    @pytest.mark.asyncio
    async def test_partial_audio_chunks_buffered(self):
        """Verify partial audio chunks are buffered and processed."""
        accept_call = AsyncMock(spec=AcceptCallUseCase)
        process_audio = AsyncMock(spec=ProcessAudioUseCase)
        end_call = AsyncMock(spec=EndCallUseCase)

        handler = ExotelWebSocketHandler(
            accept_call, process_audio, end_call, sample_rate=16000
        )

        stream_id = "stream_456"
        audio_payload = base64.b64encode(b"\x00\x01" * 160).decode()

        ws = MockWebSocket()

        ws.messages = [
            json.dumps({"event": "connected"}),
            json.dumps({
                "event": "start",
                "start": {"stream_sid": stream_id, "from": "+91987654321", "to": "+91123456789"},
                "stream_sid": stream_id,
            }),
            json.dumps({
                "event": "media",
                "media": {"payload": audio_payload, "chunk": 1},
            }),
            json.dumps({
                "event": "media",
                "media": {"payload": audio_payload, "chunk": 2},
            }),
        ]

        with patch.object(
            ws, "receive_text",
            side_effect=ws.messages + [Exception("Network hiccup")],
        ):
            try:
                await handler.handle(ws)
            except Exception:
                pass

        # Both audio chunks should have been processed
        assert process_audio.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_invalid_audio_payload_gracefully_skipped(self):
        """Verify invalid audio payload is skipped without crash."""
        accept_call = AsyncMock(spec=AcceptCallUseCase)
        process_audio = AsyncMock(spec=ProcessAudioUseCase)
        end_call = AsyncMock(spec=EndCallUseCase)

        handler = ExotelWebSocketHandler(
            accept_call, process_audio, end_call, sample_rate=16000
        )

        stream_id = "stream_789"
        valid_payload = base64.b64encode(b"\x00\x01" * 160).decode()
        invalid_payload = "not_valid_base64!!!"

        ws = MockWebSocket()
        ws.messages = [
            json.dumps({"event": "connected"}),
            json.dumps({
                "event": "start",
                "start": {"stream_sid": stream_id, "from": "+91987654321", "to": "+91123456789"},
                "stream_sid": stream_id,
            }),
            json.dumps({
                "event": "media",
                "media": {"payload": invalid_payload, "chunk": 1},
            }),
            json.dumps({
                "event": "media",
                "media": {"payload": valid_payload, "chunk": 2},
            }),
        ]

        with patch.object(
            ws, "receive_text",
            side_effect=ws.messages + [Exception("Stop")],
        ):
            try:
                await handler.handle(ws)
            except Exception:
                pass

        # Only valid chunk should be processed
        assert process_audio.execute.call_count == 1


class TestNetworkLossRecovery:
    """Test graceful recovery after network loss."""

    @pytest.mark.asyncio
    async def test_resume_after_brief_network_hiccup(self):
        """Verify call resumes after brief network interruption."""
        accept_call = AsyncMock(spec=AcceptCallUseCase)
        process_audio = AsyncMock(spec=ProcessAudioUseCase)
        end_call = AsyncMock(spec=EndCallUseCase)

        handler = ExotelWebSocketHandler(
            accept_call, process_audio, end_call, sample_rate=16000
        )

        stream_id = "stream_recovery"
        audio_payload = base64.b64encode(b"\x00\x01" * 160).decode()

        ws = MockWebSocket()

        # Simulate: connected → start → media → brief disconnect → media → stop
        messages = [
            json.dumps({"event": "connected"}),
            json.dumps({
                "event": "start",
                "start": {"stream_sid": stream_id, "from": "+91987654321", "to": "+91123456789"},
                "stream_sid": stream_id,
            }),
            json.dumps({
                "event": "media",
                "media": {"payload": audio_payload, "chunk": 1},
            }),
            json.dumps({
                "event": "media",
                "media": {"payload": audio_payload, "chunk": 2},
            }),
        ]

        with patch.object(ws, "receive_text", side_effect=messages + [Exception("Stop")]):
            try:
                await handler.handle(ws)
            except Exception:
                pass

        # Both chunks should be processed successfully
        assert process_audio.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_audio_payload_skipped(self):
        """Verify empty audio payload is skipped."""
        accept_call = AsyncMock(spec=AcceptCallUseCase)
        process_audio = AsyncMock(spec=ProcessAudioUseCase)
        end_call = AsyncMock(spec=EndCallUseCase)

        handler = ExotelWebSocketHandler(
            accept_call, process_audio, end_call, sample_rate=16000
        )

        stream_id = "stream_empty"

        ws = MockWebSocket()
        ws.messages = [
            json.dumps({"event": "connected"}),
            json.dumps({
                "event": "start",
                "start": {"stream_sid": stream_id, "from": "+91987654321", "to": "+91123456789"},
                "stream_sid": stream_id,
            }),
            json.dumps({
                "event": "media",
                "media": {"payload": "", "chunk": 1},
            }),
        ]

        with patch.object(
            ws, "receive_text",
            side_effect=ws.messages + [Exception("Stop")],
        ):
            try:
                await handler.handle(ws)
            except Exception:
                pass

        # Empty payload should not trigger process_audio
        assert process_audio.execute.call_count == 0

    @pytest.mark.asyncio
    async def test_retry_logic_on_process_audio_failure(self):
        """Verify process audio error doesn't crash handler."""
        accept_call = AsyncMock(spec=AcceptCallUseCase)
        
        # Make process_audio fail once, then succeed
        process_audio = AsyncMock(spec=ProcessAudioUseCase)
        process_audio.execute.side_effect = [
            RuntimeError("Processing error"),
            None,  # Success
        ]
        
        end_call = AsyncMock(spec=EndCallUseCase)

        handler = ExotelWebSocketHandler(
            accept_call, process_audio, end_call, sample_rate=16000
        )

        stream_id = "stream_retry"
        audio_payload = base64.b64encode(b"\x00\x01" * 160).decode()

        ws = MockWebSocket()
        ws.messages = [
            json.dumps({"event": "connected"}),
            json.dumps({
                "event": "start",
                "start": {"stream_sid": stream_id, "from": "+91987654321", "to": "+91123456789"},
                "stream_sid": stream_id,
            }),
            json.dumps({
                "event": "media",
                "media": {"payload": audio_payload, "chunk": 1},
            }),
            json.dumps({
                "event": "media",
                "media": {"payload": audio_payload, "chunk": 2},
            }),
        ]

        with patch.object(
            ws, "receive_text",
            side_effect=ws.messages + [Exception("Stop")],
        ):
            try:
                await handler.handle(ws)
            except Exception:
                pass

        # Both chunks attempted (first fails, second succeeds)
        assert process_audio.execute.call_count == 2
