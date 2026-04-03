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


class FakeCallerAudioAdapter:
    """Tracks register/unregister calls and captured sent audio."""

    def __init__(self):
        self.registered: dict = {}   # stream_id -> websocket
        self.unregistered: list = []

    def register(self, stream_id: str, websocket) -> None:
        self.registered[stream_id] = websocket

    def unregister(self, stream_id: str) -> None:
        self.unregistered.append(stream_id)


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


def _connected_msg():
    return json.dumps({"event": "connected"})


def _mark_msg(stream_id="stream-test", label="tts-done"):
    return json.dumps({
        "event": "mark",
        "stream_sid": stream_id,
        "mark": {"name": label},
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


def test_handler_registers_websocket_with_audio_adapter_on_start() -> None:
    """Critical: audio_adapter.register must be called so TTS audio can reach caller."""
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-reg")
    ws = FakeWebSocket([_start_msg("stream-reg"), _stop_msg("stream-reg")])
    audio_adapter = FakeCallerAudioAdapter()

    handler = ExotelWebSocketHandler(
        accept_call=FakeAcceptCall(session),
        process_audio=FakeProcessAudio(),
        end_call=FakeEndCall(),
        audio_adapter=audio_adapter,
    )

    asyncio.run(handler.handle(ws))

    assert "stream-reg" in audio_adapter.registered
    assert audio_adapter.registered["stream-reg"] is ws


def test_handler_unregisters_websocket_with_audio_adapter_on_stop() -> None:
    """Audio adapter must clean up on call end to avoid memory leaks."""
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-unreg")
    ws = FakeWebSocket([_start_msg("stream-unreg"), _stop_msg("stream-unreg")])
    audio_adapter = FakeCallerAudioAdapter()

    handler = ExotelWebSocketHandler(
        accept_call=FakeAcceptCall(session),
        process_audio=FakeProcessAudio(),
        end_call=FakeEndCall(),
        audio_adapter=audio_adapter,
    )

    asyncio.run(handler.handle(ws))

    assert "stream-unreg" in audio_adapter.unregistered


def test_handler_survives_connected_event_before_start() -> None:
    """Exotel sends 'connected' before 'start' — must not crash."""
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-conn")
    ws = FakeWebSocket([
        _connected_msg(),
        _start_msg("stream-conn"),
        _stop_msg("stream-conn"),
    ])

    handler = ExotelWebSocketHandler(
        accept_call=FakeAcceptCall(session),
        process_audio=FakeProcessAudio(),
        end_call=FakeEndCall(),
    )

    asyncio.run(handler.handle(ws))
    # No assertion needed — test passes if no exception raised


def test_handler_uses_exotel_chunk_number_for_sequence() -> None:
    """AudioChunk.sequence_number must come from media.chunk (Exotel's counter), not our own."""
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-seq")
    audio_b64 = base64.b64encode(bytes(3200)).decode()
    ws = FakeWebSocket([
        _start_msg("stream-seq"),
        _media_msg(42, audio_b64, "stream-seq"),   # Exotel chunk number = 42
        _stop_msg("stream-seq"),
    ])
    process_uc = FakeProcessAudio()

    handler = ExotelWebSocketHandler(
        accept_call=FakeAcceptCall(session),
        process_audio=process_uc,
        end_call=FakeEndCall(),
    )

    asyncio.run(handler.handle(ws))

    assert process_uc.chunks_received[0].sequence_number == 42


def test_handler_survives_inbound_mark_event() -> None:
    """Exotel sends 'mark' to confirm playback — must not crash."""
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-mark")
    ws = FakeWebSocket([
        _start_msg("stream-mark"),
        _mark_msg("stream-mark", "segment-1"),
        _stop_msg("stream-mark"),
    ])

    handler = ExotelWebSocketHandler(
        accept_call=FakeAcceptCall(session),
        process_audio=FakeProcessAudio(),
        end_call=FakeEndCall(),
    )

    asyncio.run(handler.handle(ws))


def _clear_msg(stream_id="stream-test"):
    return json.dumps({
        "event": "clear",
        "stream_sid": stream_id,
    })


def _start_msg_with_sample_rate(stream_id="stream-sr", sample_rate=16000):
    return json.dumps({
        "event": "start",
        "sequence_number": "1",
        "start": {
            "stream_sid": stream_id,
            "from": "+1111111111",
            "to": "+2222222222",
            "custom_parameters": {},
            "media_format": {
                "encoding": "base64",
                "sample_rate": str(sample_rate),
                "bit_rate": "128kbps"
            }
        }
    })


def test_handler_survives_inbound_clear_event() -> None:
    """Exotel sends 'clear' when caller says start over — must not crash."""
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-clr")
    ws = FakeWebSocket([
        _start_msg("stream-clr"),
        _clear_msg("stream-clr"),
        _stop_msg("stream-clr"),
    ])

    handler = ExotelWebSocketHandler(
        accept_call=FakeAcceptCall(session),
        process_audio=FakeProcessAudio(),
        end_call=FakeEndCall(),
    )

    asyncio.run(handler.handle(ws))
    # No assertion needed — test passes if no exception raised


def test_handler_reads_sample_rate_from_start_media_format() -> None:
    """Sample rate from start.media_format.sample_rate must override the default."""
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-sr")
    audio_b64 = base64.b64encode(bytes(3200)).decode()
    ws = FakeWebSocket([
        _start_msg_with_sample_rate("stream-sr", 16000),
        _media_msg(1, audio_b64, "stream-sr"),
        _stop_msg("stream-sr"),
    ])
    process_uc = FakeProcessAudio()

    handler = ExotelWebSocketHandler(
        accept_call=FakeAcceptCall(session),
        process_audio=process_uc,
        end_call=FakeEndCall(),
        sample_rate=8000,  # default 8000; should be overridden to 16000 from start message
    )

    asyncio.run(handler.handle(ws))

    assert process_uc.chunks_received[0].audio_format.sample_rate == 16000


def test_handler_closes_websocket_on_stop() -> None:
    """WebSocket must be closed after stop event so Exotel moves to next applet."""
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler

    session = _make_session("stream-close")
    ws = FakeWebSocket([_start_msg("stream-close"), _stop_msg("stream-close")])

    handler = ExotelWebSocketHandler(
        accept_call=FakeAcceptCall(session),
        process_audio=FakeProcessAudio(),
        end_call=FakeEndCall(),
    )

    asyncio.run(handler.handle(ws))

    assert ws.closed is True
