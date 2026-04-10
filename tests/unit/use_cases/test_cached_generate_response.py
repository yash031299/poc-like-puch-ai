"""Tests for CachedGenerateResponseUseCase."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.adapters.stub_embedding_model import StubEmbeddingModel
from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.entities.ai_response import AIResponse
from src.domain.entities.utterance import Utterance
from src.domain.services.semantic_cache import SemanticCache
from src.domain.value_objects.audio_format import AudioFormat
from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.use_cases.cached_generate_response import CachedGenerateResponseUseCase


class FakeSessionRepo:
    def __init__(self, session=None):
        self._store = {session.stream_identifier.value: session} if session else {}

    async def save(self, session):
        self._store[session.stream_identifier.value] = session

    async def get(self, sid):
        return self._store.get(sid)

    async def delete(self, sid):
        self._store.pop(sid, None)


class FakeLLM:
    def __init__(self, response_text: str = "Hi there!"):
        self._text = response_text

    async def generate(self, stream_id, utterance, context):
        for token in self._text.split():
            yield token + " "


class FakeRedisClient:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def setex(self, key, ttl, value):
        self._store[key] = value

    async def keys(self, pattern):
        import fnmatch
        return [k for k in self._store.keys() if fnmatch.fnmatch(str(k), pattern)]

    async def dbsize(self):
        return len(self._store)


def _make_session_with_utterance(stream_id="s1"):
    sess = ConversationSession.create(
        stream_identifier=StreamIdentifier(stream_id),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
    )
    sess.activate()
    utt = Utterance("How are you?", 0.93, True, datetime.now(timezone.utc))
    sess.add_utterance(utt)
    return sess, utt


@pytest.mark.asyncio
async def test_cached_generate_response_without_cache():
    """Use case works without cache (fallback to non-cached flow)."""
    session, utt = _make_session_with_utterance()
    repo = FakeSessionRepo(session)
    llm = FakeLLM("I am doing well!")
    use_case = CachedGenerateResponseUseCase(session_repo=repo, llm=llm)

    response = await use_case.execute(stream_id="s1", utterance_id=utt.utterance_id)

    assert response is not None
    assert response.text == "I am doing well! "
    assert response.state == "complete"


@pytest.mark.asyncio
async def test_cached_generate_response_cache_miss():
    """Cache miss results in LLM call and caching."""
    session, utt = _make_session_with_utterance()
    repo = FakeSessionRepo(session)
    llm = FakeLLM("Doing great!")
    redis = FakeRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    use_case = CachedGenerateResponseUseCase(session_repo=repo, llm=llm, cache=cache)

    response = await use_case.execute(stream_id="s1", utterance_id=utt.utterance_id)

    assert response is not None
    assert response.text == "Doing great! "
    # Verify cache now has entries
    cached = await cache.get("How are you?")
    assert cached is not None


@pytest.mark.asyncio
async def test_cached_generate_response_cache_hit():
    """Cache hit returns cached response without LLM call."""
    session, utt = _make_session_with_utterance()
    repo = FakeSessionRepo(session)

    # Mock LLM that should NOT be called
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("Should not call LLM!"))

    redis = FakeRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    use_case = CachedGenerateResponseUseCase(session_repo=repo, llm=llm, cache=cache)

    # Pre-populate cache
    cached_response = AIResponse("old-utt", datetime.now(timezone.utc))
    cached_response._text = "Cached answer!"
    cached_response._state = "complete"
    await cache.set("How are you?", cached_response)

    # Execute should hit cache
    response = await use_case.execute(stream_id="s1", utterance_id=utt.utterance_id)

    assert response is not None
    assert response.text == "Cached answer!"
    assert response.state == "complete"
    assert response.utterance_id == utt.utterance_id  # New utterance ID
    # Verify LLM was never called
    llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_cached_generate_response_stores_in_session():
    """Response is stored in session regardless of cache hit/miss."""
    session, utt = _make_session_with_utterance()
    repo = FakeSessionRepo(session)
    llm = FakeLLM("Test response")
    redis = FakeRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    use_case = CachedGenerateResponseUseCase(session_repo=repo, llm=llm, cache=cache)

    initial_response_count = len(session.ai_responses)
    response = await use_case.execute(stream_id="s1", utterance_id=utt.utterance_id)

    # Verify stored in session
    assert len(session.ai_responses) == initial_response_count + 1
    assert session.ai_responses[-1] == response


@pytest.mark.asyncio
async def test_cached_generate_response_handles_missing_session():
    """Use case raises ValueError for missing session."""
    repo = FakeSessionRepo()
    llm = FakeLLM()
    use_case = CachedGenerateResponseUseCase(session_repo=repo, llm=llm)

    with pytest.raises(ValueError, match="No active session"):
        await use_case.execute(stream_id="missing", utterance_id="utt-1")


@pytest.mark.asyncio
async def test_cached_generate_response_handles_missing_utterance():
    """Use case raises ValueError for missing utterance."""
    session, _ = _make_session_with_utterance()
    repo = FakeSessionRepo(session)
    llm = FakeLLM()
    use_case = CachedGenerateResponseUseCase(session_repo=repo, llm=llm)

    with pytest.raises(ValueError, match="Utterance not-found not found"):
        await use_case.execute(stream_id="s1", utterance_id="not-found")
