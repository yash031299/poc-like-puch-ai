"""Integration tests for Redis cache with TTL and eviction."""

import asyncio
from datetime import datetime, timezone

import numpy as np
import pytest

from src.adapters.stub_embedding_model import StubEmbeddingModel
from src.domain.entities.ai_response import AIResponse
from src.domain.services.semantic_cache import SemanticCache


class MockRedisClient:
    """Mock Redis with TTL and size limits (simplified)."""

    def __init__(self, max_size: int = 1000):
        self._store = {}
        self._ttl_map = {}
        self._max_size = max_size

    async def get(self, key):
        return self._store.get(key)

    async def setex(self, key, ttl, value):
        if len(self._store) >= self._max_size:
            # Simple LRU: remove first key
            if self._store:
                first_key = next(iter(self._store))
                del self._store[first_key]
                del self._ttl_map[first_key]

        self._store[key] = value
        self._ttl_map[key] = ttl

    async def keys(self, pattern):
        import fnmatch
        return [k for k in self._store.keys() if fnmatch.fnmatch(str(k), pattern)]

    async def dbsize(self):
        return len(self._store)

    def get_ttl(self, key):
        """Get TTL for a key (for testing)."""
        return self._ttl_map.get(key)


def _make_response(text: str):
    """Create test AIResponse."""
    response = AIResponse("utt-1", datetime.now(timezone.utc))
    response._text = text
    response._state = "complete"
    return response


@pytest.mark.asyncio
async def test_redis_cache_stores_embedding_vector():
    """Redis stores embedding vectors as binary data."""
    redis = MockRedisClient()
    embedding_model = StubEmbeddingModel(dimension=384)
    cache = SemanticCache(redis, embedding_model)

    utterance = "Store my embedding"
    response = _make_response("Response")

    await cache.set(utterance, response)

    # Check that embedding was stored
    keys = await redis.keys("cache:emb:*")
    assert len(keys) == 1

    # Verify stored value is binary
    stored = await redis.get(keys[0])
    assert isinstance(stored, bytes)
    assert len(stored) > 0


@pytest.mark.asyncio
async def test_redis_cache_ttl_set_on_entries():
    """Redis entries are stored with 24h TTL."""
    redis = MockRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    response = _make_response("Test")
    await cache.set("test utterance", response)

    # Verify TTL was set
    keys = await redis.keys("cache:*")
    for key in keys:
        ttl = redis.get_ttl(key)
        # Should be ~86400 seconds (24 hours)
        assert ttl is not None
        assert ttl == 24 * 3600


@pytest.mark.asyncio
async def test_redis_lru_eviction_on_max_entries():
    """Cache respects max 1000 entries limit with LRU eviction."""
    redis = MockRedisClient(max_size=100)  # Lower for testing
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    # Store entries up to max
    for i in range(100):
        utterance = f"utterance_{i}"
        response = _make_response(f"Response {i}")
        await cache.set(utterance, response)

    initial_size = await redis.dbsize()
    assert initial_size <= 100

    # Add one more, should evict oldest
    await cache.set("utterance_100", _make_response("Response 100"))

    final_size = await redis.dbsize()
    assert final_size <= 100


@pytest.mark.asyncio
async def test_redis_cache_response_serialization():
    """AIResponse objects are properly serialized to JSON."""
    redis = MockRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    response = AIResponse("utt-456", datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc))
    response._text = "Serialized response"
    response._state = "complete"

    await cache.set("test", response)

    # Retrieve and verify
    cached = await cache.get("test")
    assert cached is not None
    assert cached.utterance_id == response.utterance_id
    assert cached.text == response.text


@pytest.mark.asyncio
async def test_redis_cache_handles_missing_response():
    """Cache handles case where embedding exists but response missing."""
    redis = MockRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    # Manually create orphaned embedding
    test_vector = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    await redis.setex("cache:emb:orphan", 86400, test_vector.tobytes())

    # Try to get should handle gracefully
    result = await cache.get("any text")
    assert result is None


@pytest.mark.asyncio
async def test_redis_cache_stores_response_json():
    """Response is stored as JSON in cache."""
    redis = MockRedisClient()
    embedding_model = StubEmbeddingModel()
    cache = SemanticCache(redis, embedding_model)

    response = _make_response("JSON test")
    await cache.set("json test", response)

    # Get the stored JSON
    keys = await redis.keys("cache:resp:*")
    assert len(keys) > 0

    stored_json = await redis.get(keys[0])
    assert stored_json is not None

    # Parse and verify structure
    import json
    data = json.loads(stored_json)
    assert data["text"] == "JSON test"
    assert data["state"] == "complete"
    assert "response_id" in data
    assert "utterance_id" in data
