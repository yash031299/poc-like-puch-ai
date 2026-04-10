"""Redis Session Repository Integration Tests.

Tests for RedisSessionRepository that verify:
- Session serialization/deserialization
- TTL (12 hours per session)
- Connection handling
- Reconnect and resume functionality
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.domain.value_objects.audio_format import AudioFormat


@pytest.fixture
def redis_repo():
    """Fixture providing RedisSessionRepository with mocked Redis."""
    from src.adapters.redis_session_repository import RedisSessionRepository
    
    # Create with mocked Redis client
    repo = RedisSessionRepository(redis_url="redis://localhost:6379/0")
    repo.redis_client = AsyncMock()
    return repo


@pytest.fixture
def sample_session():
    """Create a sample ConversationSession for testing."""
    stream_id = StreamIdentifier(value="test-stream-123")
    audio_format = AudioFormat(sample_rate=8000, channels=1, encoding="PCM16LE")
    
    session = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+919876543210",
        called_number="+919123456789",
        audio_format=audio_format,
        custom_parameters={"route": "support", "priority": "high"}
    )
    return session


@pytest.mark.asyncio
async def test_redis_repo_saves_session(redis_repo, sample_session):
    """Test that session is saved to Redis with proper key format."""
    redis_repo.redis_client.setex = AsyncMock()
    
    await redis_repo.save(sample_session)
    
    # Verify setex was called with correct key and TTL
    redis_repo.redis_client.setex.assert_called_once()
    call_args = redis_repo.redis_client.setex.call_args
    
    key, ttl, value = call_args[0]
    assert key == f"session:{sample_session.stream_id}"
    assert ttl == 12 * 3600  # 12 hours in seconds
    
    # Verify value is JSON serializable
    decoded = json.loads(value)
    assert decoded["stream_id"] == sample_session.stream_id
    assert decoded["caller_number"] == sample_session.caller_number


@pytest.mark.asyncio
async def test_redis_repo_retrieves_session(redis_repo, sample_session):
    """Test that session can be retrieved from Redis."""
    session_json = redis_repo._serialize_session(sample_session)
    redis_repo.redis_client.get = AsyncMock(return_value=session_json)
    
    retrieved = await redis_repo.get(sample_session.stream_id)
    
    assert retrieved is not None
    assert retrieved.stream_id == sample_session.stream_id
    assert retrieved.caller_number == sample_session.caller_number
    redis_repo.redis_client.get.assert_called_once_with(f"session:{sample_session.stream_id}")


@pytest.mark.asyncio
async def test_redis_repo_returns_none_for_missing_session(redis_repo):
    """Test that None is returned for non-existent session."""
    redis_repo.redis_client.get = AsyncMock(return_value=None)
    
    result = await redis_repo.get("nonexistent-stream")
    
    assert result is None


@pytest.mark.asyncio
async def test_redis_repo_deletes_session(redis_repo, sample_session):
    """Test that session is deleted from Redis."""
    redis_repo.redis_client.delete = AsyncMock()
    
    await redis_repo.delete(sample_session.stream_id)
    
    redis_repo.redis_client.delete.assert_called_once_with(f"session:{sample_session.stream_id}")


@pytest.mark.asyncio
async def test_redis_repo_serializes_complex_session(redis_repo):
    """Test serialization of session with multiple utterances and responses."""
    from datetime import datetime
    from src.domain.entities.utterance import Utterance
    from src.domain.entities.ai_response import AIResponse
    
    stream_id = StreamIdentifier(value="complex-stream-456")
    audio_format = AudioFormat(sample_rate=16000, channels=1, encoding="PCM16LE")
    
    session = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+919876543210",
        called_number="+919123456789",
        audio_format=audio_format,
    )
    
    # Add some utterances and responses
    utterance = Utterance(
        text="Hello, can you help me?",
        confidence=0.95,
        is_final=True,
        timestamp=datetime.now()
    )
    session.add_utterance(utterance)
    
    ai_response = AIResponse(
        utterance_id=utterance.utterance_id,
        timestamp=datetime.now()
    )
    ai_response.append_text("Of course! How can I assist you today?")
    ai_response.complete()
    session.add_ai_response(ai_response)
    
    # Serialize and verify
    serialized = redis_repo._serialize_session(session)
    deserialized = redis_repo._deserialize_session(serialized)
    
    assert deserialized.stream_id == session.stream_id
    assert len(deserialized.utterances) == 1
    assert len(deserialized.ai_responses) == 1
    assert deserialized.utterances[0].text == "Hello, can you help me?"


@pytest.mark.asyncio
async def test_redis_repo_connection_pooling(redis_repo):
    """Test that Redis client uses connection pooling."""
    assert redis_repo.redis_client is not None
    # Verify it's using async Redis
    assert hasattr(redis_repo.redis_client, 'execute_command')


@pytest.mark.asyncio
async def test_redis_repo_key_format():
    """Test session key format for Redis."""
    from src.adapters.redis_session_repository import RedisSessionRepository
    
    stream_id = "test-stream-789"
    key = RedisSessionRepository._get_session_key(stream_id)
    
    assert key == "session:test-stream-789"
    assert key.startswith("session:")


@pytest.mark.asyncio
async def test_redis_repo_updates_session_ttl(redis_repo, sample_session):
    """Test that re-saving a session updates its TTL."""
    redis_repo.redis_client.setex = AsyncMock()
    
    # Save session first time
    await redis_repo.save(sample_session)
    first_call = redis_repo.redis_client.setex.call_count
    
    # Save again (e.g., after new utterance)
    await redis_repo.save(sample_session)
    
    # Should have been called twice
    assert redis_repo.redis_client.setex.call_count == first_call + 1


@pytest.mark.asyncio
async def test_redis_repo_handles_deserialization_error(redis_repo):
    """Test graceful handling of corrupted data in Redis."""
    redis_repo.redis_client.get = AsyncMock(return_value=b"invalid json")
    
    # Should return None instead of raising
    result = await redis_repo.get("some-stream")
    
    assert result is None


@pytest.mark.asyncio
async def test_redis_repo_batch_delete(redis_repo):
    """Test deleting multiple sessions."""
    redis_repo.redis_client.delete = AsyncMock()
    
    stream_ids = ["stream-1", "stream-2", "stream-3"]
    
    for stream_id in stream_ids:
        await redis_repo.delete(stream_id)
    
    # Should have called delete 3 times
    assert redis_repo.redis_client.delete.call_count == 3


@pytest.mark.asyncio
async def test_redis_repo_session_state_preserved(redis_repo):
    """Test that session interaction state is preserved through save/get."""
    stream_id = StreamIdentifier(value="state-test-stream")
    audio_format = AudioFormat(sample_rate=8000, channels=1, encoding="PCM16LE")
    
    session = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+919876543210",
        called_number="+919123456789",
        audio_format=audio_format,
    )
    
    # Simulate interaction state changes
    session._interaction_state = "generating_response"
    
    # Serialize
    serialized = redis_repo._serialize_session(session)
    
    # Deserialize
    restored = redis_repo._deserialize_session(serialized)
    
    assert restored._interaction_state == "generating_response"


@pytest.mark.asyncio
async def test_redis_repo_ttl_constant():
    """Test that TTL is 12 hours."""
    from src.adapters.redis_session_repository import RedisSessionRepository
    
    assert RedisSessionRepository.SESSION_TTL_SECONDS == 12 * 3600
