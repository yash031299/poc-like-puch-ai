"""Tests for ResetSessionUseCase — triggered when Exotel sends 'clear' event."""

import asyncio
from datetime import datetime, timezone

import pytest

from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance
from src.domain.value_objects.audio_format import AudioFormat
from src.domain.value_objects.stream_identifier import StreamIdentifier


def _make_active_session(stream_id: str = "stream-reset") -> ConversationSession:
    session = ConversationSession.create(
        stream_identifier=StreamIdentifier(stream_id),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1),
    )
    session.activate()
    return session


def _chunk(seq: int) -> AudioChunk:
    fmt = AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)
    return AudioChunk(seq, datetime.now(timezone.utc), fmt, bytes(3200))


def _utterance(text: str) -> Utterance:
    return Utterance(text, 0.95, True, datetime.now(timezone.utc))


class FakeSessionRepo:
    def __init__(self, session: ConversationSession):
        self._session = session

    async def get(self, stream_id: str):
        return self._session

    async def save(self, session: ConversationSession):
        self._session = session

    async def delete(self, stream_id: str):
        self._session = None


def test_reset_clears_utterances() -> None:
    """After reset, utterances list is empty."""
    from src.use_cases.reset_session import ResetSessionUseCase

    session = _make_active_session()
    session.add_utterance(_utterance("First thing I said"))
    session.add_utterance(_utterance("Second thing"))

    repo = FakeSessionRepo(session)
    use_case = ResetSessionUseCase(session_repo=repo)

    asyncio.run(use_case.execute("stream-reset"))

    assert session.utterances == []


def test_reset_clears_ai_responses() -> None:
    """After reset, AI responses list is empty."""
    from src.use_cases.reset_session import ResetSessionUseCase
    from src.domain.entities.ai_response import AIResponse

    session = _make_active_session()
    resp = AIResponse("u1", datetime.now(timezone.utc))
    resp.append_text("Hello")
    resp.complete()
    session.add_ai_response(resp)

    repo = FakeSessionRepo(session)
    asyncio.run(ResetSessionUseCase(session_repo=repo).execute("stream-reset"))

    assert session.ai_responses == []


def test_reset_preserves_audio_chunks() -> None:
    """Audio chunks are NOT cleared — they are part of the raw call record."""
    from src.use_cases.reset_session import ResetSessionUseCase

    session = _make_active_session()
    session.add_audio_chunk(_chunk(1))

    repo = FakeSessionRepo(session)
    asyncio.run(ResetSessionUseCase(session_repo=repo).execute("stream-reset"))

    assert len(session.audio_chunks) == 1


def test_reset_keeps_session_active() -> None:
    """Reset must not end the session — call continues."""
    from src.use_cases.reset_session import ResetSessionUseCase

    session = _make_active_session()
    repo = FakeSessionRepo(session)

    asyncio.run(ResetSessionUseCase(session_repo=repo).execute("stream-reset"))

    assert session.is_active
    assert not session.is_ended


def test_reset_raises_if_session_not_found() -> None:
    """Raises ValueError if stream_id has no active session."""
    from src.use_cases.reset_session import ResetSessionUseCase

    class EmptyRepo:
        async def get(self, sid): return None
        async def save(self, s): pass

    with pytest.raises(ValueError, match="stream-missing"):
        asyncio.run(ResetSessionUseCase(session_repo=EmptyRepo()).execute("stream-missing"))
