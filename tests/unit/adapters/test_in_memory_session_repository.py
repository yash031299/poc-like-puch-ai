"""Tests for InMemorySessionRepository adapter."""

import pytest
import asyncio
from datetime import timezone


def _make_session(stream_id: str = "stream-1"):
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat

    return ConversationSession.create(
        stream_identifier=StreamIdentifier(stream_id),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
    )


def test_save_and_get_session() -> None:
    from src.adapters.in_memory_session_repository import InMemorySessionRepository

    repo = InMemorySessionRepository()
    session = _make_session("s1")

    async def run():
        await repo.save(session)
        retrieved = await repo.get("s1")
        assert retrieved == session

    asyncio.run(run())


def test_get_returns_none_for_unknown_stream() -> None:
    from src.adapters.in_memory_session_repository import InMemorySessionRepository

    repo = InMemorySessionRepository()

    async def run():
        result = await repo.get("no-such-stream")
        assert result is None

    asyncio.run(run())


def test_delete_removes_session() -> None:
    from src.adapters.in_memory_session_repository import InMemorySessionRepository

    repo = InMemorySessionRepository()
    session = _make_session("s2")

    async def run():
        await repo.save(session)
        await repo.delete("s2")
        result = await repo.get("s2")
        assert result is None

    asyncio.run(run())


def test_delete_nonexistent_is_idempotent() -> None:
    from src.adapters.in_memory_session_repository import InMemorySessionRepository

    repo = InMemorySessionRepository()

    async def run():
        # Should not raise
        await repo.delete("ghost")

    asyncio.run(run())


def test_save_overwrites_existing_session() -> None:
    from src.adapters.in_memory_session_repository import InMemorySessionRepository

    repo = InMemorySessionRepository()
    session = _make_session("s3")

    async def run():
        await repo.save(session)
        session.activate()
        await repo.save(session)
        retrieved = await repo.get("s3")
        assert retrieved.call_session.state == "active"

    asyncio.run(run())


def test_concurrent_save_and_get() -> None:
    """Multiple coroutines saving/getting different sessions don't interfere."""
    from src.adapters.in_memory_session_repository import InMemorySessionRepository

    repo = InMemorySessionRepository()
    sessions = [_make_session(f"stream-{i}") for i in range(5)]

    async def run():
        await asyncio.gather(*(repo.save(s) for s in sessions))
        results = await asyncio.gather(*(repo.get(f"stream-{i}") for i in range(5)))
        for i, result in enumerate(results):
            assert result == sessions[i]

    asyncio.run(run())
