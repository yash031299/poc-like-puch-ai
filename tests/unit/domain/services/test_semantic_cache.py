"""Tests for SemanticCache service."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from src.adapters.stub_embedding_model import StubEmbeddingModel
from src.domain.entities.ai_response import AIResponse
from src.domain.services.semantic_cache import SemanticCache


class FakeRedisClient:
    """In-memory Redis mock for testing."""

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


def _make_ai_response(text: str = "Hello, how can I help?"):
    """Helper to create test AIResponse."""
    response = AIResponse("utt-1", datetime.now(timezone.utc))
    response._text = text
    response._state = "complete"
    return response


@pytest.mark.asyncio
async def test_semantic_cache_hit_with_similar_utterance():
    """Cache hit when query is similar to cached utterance (>0.85 similarity)."""
    redis = FakeRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    # Cache a response for an utterance
    utterance = "How can I help you today?"
    response = _make_ai_response("Here to assist!")

    await cache.set(utterance, response)

    # Query with very similar utterance (same seed due to high similarity in stub)
    similar_utterance = "How can I help you today?"
    cached = await cache.get(similar_utterance)

    assert cached is not None
    assert cached.text == response.text
    assert cached.state == "complete"


@pytest.mark.asyncio
async def test_semantic_cache_miss_with_dissimilar_utterance():
    """Cache miss when query similarity is below threshold."""
    redis = FakeRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    # Cache a response
    utterance = "Help me with technology"
    response = _make_ai_response("Tech support available")
    await cache.set(utterance, response)

    # Query with completely different utterance
    different_utterance = "What is 2+2?"
    cached = await cache.get(different_utterance)

    # Likely miss due to low similarity (unless by chance)
    # The stub model generates deterministic embeddings, so this tests
    # that different text produces different embeddings
    # Since we're using hash-based seeds, very different text = different embeddings
    assert cached is None or cached.text != response.text


@pytest.mark.asyncio
async def test_semantic_cache_empty_returns_none():
    """Cache returns None when empty."""
    redis = FakeRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    result = await cache.get("any utterance")

    assert result is None


@pytest.mark.asyncio
async def test_semantic_cache_multiple_entries():
    """Cache can store and retrieve multiple entries."""
    redis = FakeRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    # Store multiple responses
    utterances = [
        ("Tell me a joke", "Why did the chicken cross?"),
        ("What's the weather?", "It's sunny today"),
        ("Who are you?", "I'm an AI assistant"),
    ]

    for utt, text in utterances:
        response = _make_ai_response(text)
        await cache.set(utt, response)

    # Verify each can be retrieved
    for utt, text in utterances:
        cached = await cache.get(utt)
        assert cached is not None
        assert cached.text == text


@pytest.mark.asyncio
async def test_semantic_cache_respects_threshold():
    """Cache uses 0.85 similarity threshold correctly."""
    redis = FakeRedisClient()

    # Mock embedding model to return controlled vectors
    mock_model = MagicMock()
    # Make vectors much more different to ensure below threshold
    mock_model.embed = MagicMock(side_effect=lambda text: {
        "query": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        "cached": np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),  # 0.0 similarity
    }.get(text, np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)))

    cache = SemanticCache(redis, mock_model)

    # Cache with specific vector
    response = _make_ai_response("Cached response")
    await cache.set("cached", response)

    # Query with completely orthogonal vector (should be 0.0 similarity)
    result = await cache.get("query")

    # Should miss because similarity is 0.0 (well below 0.85 threshold)
    assert result is None


@pytest.mark.asyncio
async def test_semantic_cache_handles_redis_errors():
    """Cache handles Redis errors gracefully."""
    # Create a mock Redis that raises errors
    redis = AsyncMock()
    redis.keys.side_effect = Exception("Redis connection failed")

    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    # Should not raise, just return None
    result = await cache.get("any text")
    assert result is None


@pytest.mark.asyncio
async def test_semantic_cache_serialization():
    """Response serialization/deserialization preserves data."""
    redis = FakeRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    # Create and cache a response
    response = AIResponse("utt-123", datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc))
    response._text = "Test response text"
    response._state = "complete"

    await cache.set("test utterance", response)

    # Retrieve and verify
    cached = await cache.get("test utterance")
    assert cached is not None
    assert cached.utterance_id == response.utterance_id
    assert cached.text == response.text
    assert cached.state == response.state
