"""Tests for StreamResponseUseCase."""

import pytest
import asyncio
from datetime import datetime, timezone


class FakeSessionRepo:
    def __init__(self, session=None):
        self._store = {session.stream_identifier.value: session} if session else {}

    async def save(self, session): self._store[session.stream_identifier.value] = session
    async def get(self, sid): return self._store.get(sid)
    async def delete(self, sid): self._store.pop(sid, None)


class FakeTTS:
    async def synthesize(self, stream_id, response):
        from src.domain.entities.speech_segment import SpeechSegment
        from src.domain.value_objects.audio_format import AudioFormat
        fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
        yield SpeechSegment(response.response_id, 0, bytes(3200), fmt, False, datetime.now(timezone.utc))
        yield SpeechSegment(response.response_id, 1, bytes(3200), fmt, True, datetime.now(timezone.utc))


class FakeCallerAudio:
    def __init__(self):
        self.sent = []

    async def send_segment(self, stream_id, segment):
        self.sent.append((stream_id, segment))


def _make_session_with_response(stream_id="s1"):
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance
    from src.domain.entities.ai_response import AIResponse

    sess = ConversationSession.create(
        stream_identifier=StreamIdentifier(stream_id),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
    )
    sess.activate()
    utt = Utterance("Hello", 0.95, True, datetime.now(timezone.utc))
    sess.add_utterance(utt)
    resp = AIResponse(utt.utterance_id, datetime.now(timezone.utc))
    resp.append_text("Hi there!")
    resp.complete()
    sess.add_ai_response(resp)
    return sess, resp


def test_stream_response_sends_segments_to_caller() -> None:
    from src.use_cases.stream_response import StreamResponseUseCase

    session, resp = _make_session_with_response()
    repo = FakeSessionRepo(session)
    tts = FakeTTS()
    audio_out = FakeCallerAudio()
    use_case = StreamResponseUseCase(session_repo=repo, tts=tts, audio_out=audio_out)

    async def run():
        await use_case.execute(stream_id="s1", response_id=resp.response_id)

    asyncio.run(run())

    # Two segments sent to caller
    assert len(audio_out.sent) == 2
    assert audio_out.sent[0][0] == "s1"
    assert audio_out.sent[1][1].is_last is True

    # Segments stored in session
    assert len(session.speech_segments) == 2

    # Response marked delivered
    assert resp.state == "delivered"
    assert session.interaction_state == "listening"


def test_stream_response_raises_if_response_not_found() -> None:
    from src.use_cases.stream_response import StreamResponseUseCase

    session, _ = _make_session_with_response()
    repo = FakeSessionRepo(session)
    use_case = StreamResponseUseCase(session_repo=repo, tts=FakeTTS(), audio_out=FakeCallerAudio())

    async def run():
        with pytest.raises(ValueError, match="AIResponse bad-id not found"):
            await use_case.execute(stream_id="s1", response_id="bad-id")

    asyncio.run(run())
