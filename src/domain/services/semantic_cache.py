"""SemanticCache — Redis-backed caching service using embedding similarity."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from src.domain.entities.ai_response import AIResponse

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.85
_CACHE_TTL_SECONDS = 24 * 3600  # 24 hours
_MAX_CACHE_ENTRIES = 1000


class SemanticCache:
    """
    Caches AIResponse objects keyed by semantic similarity of user utterances.

    Uses embedding vectors to match similar utterances (cosine similarity >0.85).
    Stores serialized AIResponse objects in Redis with TTL=24h and LRU eviction.
    """

    def __init__(self, redis_client, embedding_model):
        """
        Initialize SemanticCache.

        Args:
            redis_client: Redis async client (redis.asyncio.Redis)
            embedding_model: Model that generates embeddings (callable or object
                           with embed() method returning numpy array)
        """
        self._redis = redis_client
        self._embeddings = embedding_model
        self._ttl = _CACHE_TTL_SECONDS
        self._threshold = _SIMILARITY_THRESHOLD
        self._max_entries = _MAX_CACHE_ENTRIES

    async def get(self, utterance: str) -> Optional[AIResponse]:
        """
        Retrieve cached AIResponse if similar utterance exists (>0.85 similarity).

        Args:
            utterance: The user utterance to search for

        Returns:
            Cached AIResponse if hit (similarity >0.85), None otherwise
        """
        try:
            # Generate embedding for query utterance
            query_embedding = self._embeddings.embed(utterance)
            query_vector = np.array(query_embedding, dtype=np.float32)

            # Get all cached embeddings (keys: "cache:emb:<hash>")
            keys = await self._redis.keys("cache:emb:*")
            if not keys:
                logger.debug("Cache miss for utterance (no cached entries)")
                return None

            best_similarity = -1.0
            best_key = None

            # Find best matching embedding
            for key in keys:
                # Normalize key to string
                key_str = key.decode() if isinstance(key, bytes) else str(key)
                raw_vec = await self._redis.get(key_str)
                if not raw_vec:
                    continue

                cached_vector = np.frombuffer(raw_vec, dtype=np.float32)

                # Cosine similarity
                similarity = self._cosine_similarity(query_vector, cached_vector)

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_key = key_str

            if best_similarity < self._threshold:
                logger.debug(
                    "Cache miss for utterance (best similarity=%.3f < %.3f)",
                    best_similarity,
                    self._threshold,
                )
                return None

            # Retrieve response using the matching key
            response_key = best_key.replace("cache:emb:", "cache:resp:")
            cached_response_json = await self._redis.get(response_key)
            if not cached_response_json:
                logger.debug("Cache miss (embedding found but response missing)")
                return None

            # Deserialize response
            response_data = json.loads(cached_response_json)
            response = self._deserialize_response(response_data)

            logger.info(
                "Cache hit for utterance (similarity=%.3f)",
                best_similarity,
            )
            return response

        except Exception as e:
            logger.error("Error retrieving from cache: %s", e)
            return None

    async def set(self, utterance: str, response: AIResponse) -> None:
        """
        Store AIResponse with embedding-based key for similarity search.

        Args:
            utterance: The user utterance
            response: The AIResponse to cache
        """
        try:
            # Generate embedding
            query_embedding = self._embeddings.embed(utterance)
            query_vector = np.array(query_embedding, dtype=np.float32)

            # Create cache key from utterance hash
            cache_key = hashlib.sha256(utterance.encode()).hexdigest()[:16]

            # Store embedding vector
            emb_key = f"cache:emb:{cache_key}"
            await self._redis.setex(
                emb_key,
                self._ttl,
                query_vector.tobytes(),
            )

            # Store response as JSON
            resp_key = f"cache:resp:{cache_key}"
            serialized = self._serialize_response(response)
            await self._redis.setex(
                resp_key,
                self._ttl,
                json.dumps(serialized),
            )

            # Check entry count and evict oldest if needed
            cache_size = await self._redis.dbsize()
            if cache_size > self._max_entries:
                # Redis will handle LRU eviction policy if configured
                logger.warning(
                    "Cache size exceeded max entries (%d/%d)",
                    cache_size,
                    self._max_entries,
                )

            logger.debug("Cached response for utterance (key=%s)", cache_key)

        except Exception as e:
            logger.error("Error storing in cache: %s", e)

    @staticmethod
    def _cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        norm_v1 = np.linalg.norm(v1)
        norm_v2 = np.linalg.norm(v2)

        if norm_v1 == 0 or norm_v2 == 0:
            return 0.0

        return float(np.dot(v1, v2) / (norm_v1 * norm_v2))

    @staticmethod
    def _serialize_response(response: AIResponse) -> dict:
        """Serialize AIResponse to JSON-compatible dict."""
        return {
            "response_id": response.response_id,
            "utterance_id": response.utterance_id,
            "timestamp": response.timestamp.isoformat(),
            "text": response.text,
            "state": response.state,
        }

    @staticmethod
    def _deserialize_response(data: dict) -> AIResponse:
        """Deserialize AIResponse from dict."""
        response = AIResponse(
            utterance_id=data["utterance_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )
        # Restore text and state
        if data["text"]:
            response._text = data["text"]
        response._state = data["state"]
        response._response_id = data["response_id"]
        return response
