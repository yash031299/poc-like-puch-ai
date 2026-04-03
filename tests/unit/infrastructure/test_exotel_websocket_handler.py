"""Tests for ExotelWebSocketHandler — uses FakeWebSocket and Fakes for use cases."""

import asyncio
import json
import base64
import pytest
from datetime import datetime, timezone


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeWebSocket:
    """Simulates a FastAPI WebSocket for testing."""

    def __init__(self, messages: list):
        self._in = list(messages)
        self.sent = []
        self.closed = False
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        if self._in:
            return self._in.pop(0)
        raise RuntimeError("No more messages")

    async def send_text(self, data: str):
        self.sent.append(json.loads(data))

    async def close(self):
        self.closed = True


class FakeAcceptCall:
    def __init__(self, session):
        self._session = session
        self.called_with = None

    async def execute(self, **kwargs):
        self.called_with = kwargs
        return self._session


class FakeProcessAudio:
    def __init__(self):
        self.chunks_received = []

    async def execute(self, stream_id, chunk):
        self.chunks_received.append(chunk)
        return []  # No utterances for simplicity in this test


class FakeEndCall:
    def __init__(self):
        self.ended = []

    async def execute(self, stream_id):
        self.ended.append(stream_id)


def _make_session(stream_id="stream-test"):
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat

    sess = ConversationSession.create(
        stream_identifier=StreamIdentifier(stream_id),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
    )
    sess.activate()
    return sess


# ── Message helpers ───────────────────────────────────────────────────────────

def _start_msg(stream_id="stream-test", caller="+1111111111", called="+2222222222"):
    return json.dumps({
        "event": "start",
        "sequence_number": "1",
        "start": {
            "stream_sid": stream_id,
            "from": caller,
            "to": called,
            "custom_parameters": {}
        }
    })


def _media_msg(seq: int, audio_b64: str, stream_id="stream-test"):
    return json.dumps({
        "event": "media",
        "sequence_number": str(seq),
        "stream_sid": stream_id,
        "media": {
            "chunk": str(seq),
            "timestamp": "100",
            "payload": audio_b64
        }
    })


def _stop_msg(stream_id="stream-test"):
    return json.dumps({
        "event": "stop",
        "sequence_number": "99",
        "stream_sid": stream_id,
        "stop": {"stream_sid": stream_id}
    })


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_handler_accepts_websocket_on_connect() -> None:
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session()
    ws = FakeWebSocket([_stop_msg()])
    accept_uc = FakeAcceptCall(session)
    end_uc = FakeEndCall()

    handler = ExotelWebSocketHandler(
        accept_call=accept_uc,
        process_audio=FakeProcessAudio(),
        end_call=end_uc,
    )

    async def run():
        await handler.handle(ws)

    asyncio.run(run())
    assert ws.accepted is True


def test_handler_calls_accept_use_case_on_start_event() -> None:
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-abc")
    ws = FakeWebSocket([_start_msg("stream-abc"), _stop_msg("stream-abc")])
    accept_uc = FakeAcceptCall(session)
    end_uc = FakeEndCall()

    handler = ExotelWebSocketHandler(
        accept_call=accept_uc,
        process_audio=FakeProcessAudio(),
        end_call=end_uc,
    )

    asyncio.run(handler.handle(ws))

    assert accept_uc.called_with is not None
    assert accept_uc.called_with["stream_id"] == "stream-abc"
    assert accept_uc.called_with["caller_number"] == "+1111111111"


def test_handler_calls_process_audio_on_media_event() -> None:
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-m")
    audio_b64 = base64.b64encode(bytes(3200)).decode()
    ws = FakeWebSocket([
        _start_msg("stream-m"),
        _media_msg(1, audio_b64, "stream-m"),
        _stop_msg("stream-m"),
    ])
    accept_uc = FakeAcceptCall(session)
    process_uc = FakeProcessAudio()
    end_uc = FakeEndCall()

    handler = ExotelWebSocketHandler(
        accept_call=accept_uc,
        process_audio=process_uc,
        end_call=end_uc,
    )

    asyncio.run(handler.handle(ws))

    assert len(process_uc.chunks_received) == 1
    assert process_uc.chunks_received[0].size_bytes == 3200


def test_handler_calls_end_call_on_stop_event() -> None:
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-e")
    ws = FakeWebSocket([_start_msg("stream-e"), _stop_msg("stream-e")])
    accept_uc = FakeAcceptCall(session)
    end_uc = FakeEndCall()

    handler = ExotelWebSocketHandler(
        accept_call=accept_uc,
        process_audio=FakeProcessAudio(),
        end_call=end_uc,
    )

    asyncio.run(handler.handle(ws))

    assert "stream-e" in end_uc.ended
