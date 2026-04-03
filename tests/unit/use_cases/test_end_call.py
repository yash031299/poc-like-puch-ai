"""Tests for EndCallUseCase."""

import pytest
import asyncio
from datetime import datetime, timezone


class FakeSessionRepo:
    def __init__(self, session=None):
        self._store = {session.stream_identifier.value: session} if session else {}

    async def save(self, session): self._store[session.stream_identifier.value] = session
    async def get(self, sid): return self._store.get(sid)
    async def delete(self, sid): self._store.pop(sid, None)


def _make_active_session(stream_id="s1"):
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


def test_end_call_marks_session_ended_and_removes_from_repo() -> None:
    from src.use_cases.end_call import EndCallUseCase

    session = _make_active_session("s1")
    repo = FakeSessionRepo(session)
    use_case = EndCallUseCase(session_repo=repo)

    async def run():
        await use_case.execute(stream_id="s1")

    asyncio.run(run())

    assert session.is_ended is True
    # Session removed from repo after call ends
    remaining = asyncio.run(repo.get("s1"))
    assert remaining is None


def test_end_call_raises_if_session_not_found() -> None:
    from src.use_cases.end_call import EndCallUseCase

    repo = FakeSessionRepo()
    use_case = EndCallUseCase(session_repo=repo)

    async def run():
        with pytest.raises(ValueError, match="No active session for stream missing"):
            await use_case.execute(stream_id="missing")

    asyncio.run(run())
