"""Tests for AcceptCallUseCase — uses Fakes, no infrastructure."""

import pytest
import asyncio
from datetime import datetime, timezone


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeSessionRepo:
    def __init__(self):
        self._store = {}

    async def save(self, session):
        self._store[session.stream_identifier.value] = session

    async def get(self, stream_id):
        return self._store.get(stream_id)

    async def delete(self, stream_id):
        self._store.pop(stream_id, None)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_accept_call_creates_and_saves_session() -> None:
    from src.use_cases.accept_call import AcceptCallUseCase
    from src.domain.value_objects.audio_format import AudioFormat

    repo = FakeSessionRepo()
    use_case = AcceptCallUseCase(session_repo=repo)

    async def run():
        return await use_case.execute(
            stream_id="stream-001",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
        )

    session = asyncio.run(run())

    assert session is not None
    assert session.stream_identifier.value == "stream-001"
    assert session.call_session.state == "active"

    saved = asyncio.run(repo.get("stream-001"))
    assert saved == session


def test_accept_call_with_custom_parameters() -> None:
    from src.use_cases.accept_call import AcceptCallUseCase
    from src.domain.value_objects.audio_format import AudioFormat

    repo = FakeSessionRepo()
    use_case = AcceptCallUseCase(session_repo=repo)

    async def run():
        return await use_case.execute(
            stream_id="stream-003",
            caller_number="+1111111111",
            called_number="+2222222222",
            audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
            custom_parameters={"language": "en-US"},
        )

    session = asyncio.run(run())
    assert session.call_session.custom_parameters == {"language": "en-US"}


def test_accept_call_raises_if_stream_already_exists() -> None:
    from src.use_cases.accept_call import AcceptCallUseCase
    from src.domain.value_objects.audio_format import AudioFormat

    repo = FakeSessionRepo()
    use_case = AcceptCallUseCase(session_repo=repo)
    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

    async def run():
        await use_case.execute("stream-dup", "+1111111111", "+2222222222", fmt)
        with pytest.raises(ValueError, match="Session already exists for stream stream-dup"):
            await use_case.execute("stream-dup", "+1111111111", "+2222222222", fmt)

    asyncio.run(run())
