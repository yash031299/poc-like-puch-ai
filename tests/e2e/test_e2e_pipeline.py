"""End-to-end pipeline integration tests.

Proves the complete voice AI pipeline from Exotel WebSocket input to
audio output works with Fake implementations of all external services.

Pipeline: Exotel WS → start/media/stop → STT → LLM → TTS → audio back to caller
"""

import asyncio
import base64
import json
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import pytest

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.ai_response import AIResponse
from src.domain.entities.speech_segment import SpeechSegment
from src.domain.entities.utterance import Utterance
from src.domain.value_objects.audio_format import AudioFormat
from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.ports.caller_audio_port import CallerAudioPort
from src.ports.language_model_port import LanguageModelPort
from src.ports.speech_to_text_port import SpeechToTextPort


# ── Fakes for all external services ───────────────────────────────────────────

class FakeSTT(SpeechToTextPort):
    """Returns a fixed transcription for any audio chunk."""

    def __init__(self, transcript: str = "Hello, how are you?"):
        self._transcript = transcript
        self.chunks_received: list[AudioChunk] = []

    async def transcribe(self, stream_id: str, chunk: AudioChunk) -> AsyncIterator[Utterance]:
        self.chunks_received.append(chunk)
        yield Utterance(
            text=self._transcript,
            confidence=0.98,
            is_final=True,
            timestamp=datetime.now(timezone.utc),
        )


class FakeLLM(LanguageModelPort):
    """Returns a fixed AI response for any utterance."""

    def __init__(self, response: str = "I am doing well, thank you!"):
        self._response = response
        self.utterances_received: list[Utterance] = []

    async def generate(self, stream_id: str, utterance: Utterance, context: list) -> AsyncIterator[str]:
        self.utterances_received.append(utterance)
        # Yield in chunks to simulate streaming
        words = self._response.split()
        for word in words:
            yield word + " "


class FakeTTS:
    """Returns fixed 3200-byte audio for any AI response."""

    def __init__(self):
        self.responses_received: list[AIResponse] = []

    async def synthesize(self, stream_id: str, response: AIResponse) -> AsyncIterator[SpeechSegment]:
        self.responses_received.append(response)
        fmt = AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)
        # Return 2 segments: one intermediate + one final
        yield SpeechSegment("r1", 0, bytes(3200), fmt, False, datetime.now(timezone.utc))
        yield SpeechSegment("r1", 1, bytes(3200), fmt, True, datetime.now(timezone.utc))


class FakeCallerAudio(CallerAudioPort):
    """Captures all audio segments sent to the caller."""

    def __init__(self):
        self.sent_segments: list[SpeechSegment] = []
        self.registered: dict = {}
        self.unregistered: list = []

    def register(self, stream_id: str, websocket, sample_rate=None) -> None:
        self.registered[stream_id] = websocket

    def unregister(self, stream_id: str) -> None:
        self.unregistered.append(stream_id)

    async def send_segment(self, stream_id: str, segment: SpeechSegment) -> None:
        self.sent_segments.append(segment)


class FakeWebSocket:
    """Simulates Exotel's WebSocket sending start → media → stop."""

    def __init__(self, messages: list):
        self._in = list(messages)
        self.sent = []
        self.closed = False
        self.accepted = False
        # Mock client IP for rate limiting tests
        self.client = type('obj', (object,), {'host': '127.0.0.1'})()

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        if self._in:
            return self._in.pop(0)
        raise RuntimeError("connection closed")

    async def send_text(self, data: str):
        self.sent.append(json.loads(data))

    async def close(self, code=None, reason=None):
        self.closed = True


def _make_pipeline(stt=None, llm=None, tts=None, audio_out=None):
    """Wire the full pipeline and return handler + all fakes."""
    from src.adapters.in_memory_session_repository import InMemorySessionRepository
    from src.infrastructure.exotel_websocket_handler import ExotelWebSocketHandler
    from src.use_cases.accept_call import AcceptCallUseCase
    from src.use_cases.end_call import EndCallUseCase
    from src.use_cases.generate_response import GenerateResponseUseCase
    from src.use_cases.process_audio import ProcessAudioUseCase
    from src.use_cases.stream_response import StreamResponseUseCase

    repo = InMemorySessionRepository()
    stt = stt or FakeSTT()
    llm = llm or FakeLLM()
    tts = tts or FakeTTS()
    audio_out = audio_out or FakeCallerAudio()

    accept_uc = AcceptCallUseCase(session_repo=repo)
    generate_uc = GenerateResponseUseCase(session_repo=repo, llm=llm)
    stream_uc = StreamResponseUseCase(session_repo=repo, tts=tts, audio_out=audio_out)
    process_uc = ProcessAudioUseCase(
        session_repo=repo,
        stt=stt,
        generate_response=generate_uc,
        stream_response=stream_uc,
    )
    end_uc = EndCallUseCase(session_repo=repo)

    handler = ExotelWebSocketHandler(
        accept_call=accept_uc,
        process_audio=process_uc,
        end_call=end_uc,
        session_repo=repo,
        sample_rate=8000,
        audio_adapter=audio_out,
    )
    return handler, stt, llm, tts, audio_out, repo


def _exotel_messages(stream_id: str = "e2e-stream-001") -> list:
    """Build the exact sequence Exotel sends for one call."""
    audio_b64 = base64.b64encode(bytes(3200)).decode()
    return [
        json.dumps({"event": "connected"}),
        json.dumps({
            "event": "start",
            "sequence_number": "1",
            "stream_sid": stream_id,
            "start": {
                "stream_sid": stream_id,
                "call_sid": "call-abc",
                "account_sid": "acct-xyz",
                "from": "+91XXXXXXXXXX",
                "to": "+1800XXXXXXX",
                "custom_parameters": {},
                "media_format": {
                    "encoding": "base64",
                    "sample_rate": "8000",
                    "bit_rate": "128kbps",
                },
            },
        }),
        json.dumps({
            "event": "media",
            "sequence_number": "2",
            "stream_sid": stream_id,
            "media": {"chunk": "1", "timestamp": "100", "payload": audio_b64},
        }),
        json.dumps({
            "event": "stop",
            "sequence_number": "3",
            "stream_sid": stream_id,
            "stop": {"call_sid": "call-abc", "account_sid": "acct-xyz", "reason": "callended"},
        }),
    ]


# ── End-to-end tests ──────────────────────────────────────────────────────────

def test_e2e_full_call_flow_start_to_stop() -> None:
    """
    End-to-end: Exotel sends connected→start→media→stop.
    Handler must:
    1. Accept WebSocket
    2. Create session on start
    3. Process audio on media
    4. Trigger STT → LLM → TTS → send audio back
    5. End session on stop
    """
    handler, stt, llm, tts, audio_out, repo = _make_pipeline()
    ws = FakeWebSocket(_exotel_messages())

    asyncio.run(handler.handle(ws))

    assert ws.accepted is True
    assert ws.closed is True


def test_e2e_stt_receives_audio_from_exotel() -> None:
    """STT adapter must receive the audio chunk Exotel sent."""
    stt = FakeSTT("What can you do?")
    handler, stt, _, _, _, _ = _make_pipeline(stt=stt)
    ws = FakeWebSocket(_exotel_messages())

    asyncio.run(handler.handle(ws))

    assert len(stt.chunks_received) == 1
    assert stt.chunks_received[0].audio_format.sample_rate == 8000


def test_e2e_llm_receives_stt_transcription() -> None:
    """LLM adapter must receive the utterance from STT."""
    stt = FakeSTT("What services do you offer?")
    llm = FakeLLM("We offer 24/7 support.")
    handler, _, llm, _, _, _ = _make_pipeline(stt=stt, llm=llm)
    ws = FakeWebSocket(_exotel_messages())

    asyncio.run(handler.handle(ws))

    assert len(llm.utterances_received) == 1
    assert llm.utterances_received[0].text == "What services do you offer?"


def test_e2e_tts_receives_llm_response() -> None:
    """TTS adapter must receive the completed AI response from LLM."""
    llm = FakeLLM("Hello, I am your AI assistant.")
    tts = FakeTTS()
    handler, _, _, tts, _, _ = _make_pipeline(llm=llm, tts=tts)
    ws = FakeWebSocket(_exotel_messages())

    asyncio.run(handler.handle(ws))

    assert len(tts.responses_received) == 1
    assert "Hello" in tts.responses_received[0].text


def test_e2e_audio_segments_sent_back_to_caller() -> None:
    """Audio from TTS must be sent back via CallerAudioPort."""
    audio_out = FakeCallerAudio()
    handler, _, _, _, audio_out, _ = _make_pipeline(audio_out=audio_out)
    ws = FakeWebSocket(_exotel_messages())

    asyncio.run(handler.handle(ws))

    # FakeTTS yields 2 segments; both must reach the caller
    assert len(audio_out.sent_segments) == 2
    assert all(seg.size_bytes == 3200 for seg in audio_out.sent_segments)
    assert audio_out.sent_segments[-1].is_last is True


def test_e2e_session_cleaned_up_after_stop() -> None:
    """Session must be removed from repo after stop event."""
    handler, _, _, _, _, repo = _make_pipeline()
    ws = FakeWebSocket(_exotel_messages())

    asyncio.run(handler.handle(ws))

    # Session should be deleted from repo after call ends
    assert len(repo) == 0


def test_e2e_websocket_registered_and_unregistered() -> None:
    """Audio adapter must register WS on start and unregister on stop."""
    audio_out = FakeCallerAudio()
    handler, _, _, _, audio_out, _ = _make_pipeline(audio_out=audio_out)
    ws = FakeWebSocket(_exotel_messages("stream-reg-test"))

    asyncio.run(handler.handle(ws))

    # Registered on start, unregistered on stop
    assert "stream-reg-test" in audio_out.registered
    assert "stream-reg-test" in audio_out.unregistered


def test_e2e_multiple_calls_isolated() -> None:
    """Two simultaneous calls must not interfere with each other."""
    handler1, _, _, tts1, audio1, _ = _make_pipeline(tts=FakeTTS(), audio_out=FakeCallerAudio())
    handler2, _, _, tts2, audio2, _ = _make_pipeline(tts=FakeTTS(), audio_out=FakeCallerAudio())

    ws1 = FakeWebSocket(_exotel_messages("call-001"))
    ws2 = FakeWebSocket(_exotel_messages("call-002"))

    async def run_both():
        await asyncio.gather(handler1.handle(ws1), handler2.handle(ws2))

    asyncio.run(run_both())

    # Each call got its own audio response
    assert len(audio1.sent_segments) == 2
    assert len(audio2.sent_segments) == 2
    assert ws1.closed is True
    assert ws2.closed is True
