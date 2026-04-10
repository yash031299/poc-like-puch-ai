"""
Integration tests for distributed session locking.

Tests that verify two instances cannot concurrently handle the same stream,
and that locks are properly released even on errors.

Note: Requires Redis running (use docker-compose from ops/ or mock)
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.adapters.redis_session_repository import RedisSessionRepository
from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.domain.value_objects.audio_format import AudioFormat


@pytest.fixture
def audio_format():
    """Create standard audio format fixture."""
    return AudioFormat(sample_rate=8000, channels=1, encoding="PCM16LE")


@pytest.fixture
def session_fixture(audio_format):
    """Create a test ConversationSession."""
    return ConversationSession.create(
        stream_identifier=StreamIdentifier(value="test-stream-123"),
        caller_number="+1234567890",
        called_number="+9876543210",
        audio_format=audio_format,
        custom_parameters={},
    )


class TestSessionLocking:
    """Test distributed locking for concurrent stream access."""

    @pytest.mark.asyncio
    async def test_lock_acquisition_and_release(self):
        """Test basic lock acquisition and release."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-001"

        # Mock Redis client
        repo.redis_client = AsyncMock()
        repo.redis_client.set = AsyncMock(return_value=True)
        repo.redis_client.delete = AsyncMock(return_value=1)

        # Acquire lock
        acquired = await repo.acquire_lock(stream_id)
        assert acquired, "Lock should be acquired"
        repo.redis_client.set.assert_called_once()

        # Release lock
        await repo.release_lock(stream_id)
        repo.redis_client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_lock_contention_prevents_concurrent_access(self):
        """Test that lock prevents concurrent access from different instances."""
        repo1 = RedisSessionRepository("redis://localhost:6379/0")
        repo2 = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-002"

        # Mock: repo1 gets lock, repo2 blocked
        repo1.redis_client = AsyncMock()
        repo1.redis_client.set = AsyncMock(return_value=True)
        repo1.redis_client.delete = AsyncMock(return_value=1)

        repo2.redis_client = AsyncMock()
        repo2.redis_client.set = AsyncMock(return_value=False)  # Lock held by repo1

        # repo1 acquires lock
        acquired1 = await repo1.acquire_lock(stream_id)
        assert acquired1, "repo1 should acquire lock"

        # repo2 blocked
        acquired2 = await repo2.acquire_lock(stream_id)
        assert not acquired2, "repo2 should be blocked (lock held by repo1)"

    @pytest.mark.asyncio
    async def test_lock_context_manager_acquires_and_releases(self):
        """Test stream_lock context manager handles acquire/release."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-003"

        repo.redis_client = AsyncMock()
        repo.redis_client.set = AsyncMock(return_value=True)
        repo.redis_client.delete = AsyncMock(return_value=1)

        # Use context manager
        async with repo.stream_lock(stream_id):
            # Inside context: lock should be held
            repo.redis_client.set.assert_called()

        # After context: lock should be released
        repo.redis_client.delete.assert_called()

    @pytest.mark.asyncio
    async def test_lock_context_manager_retries_on_contention(self):
        """Test exponential backoff on lock contention."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-004"

        repo.redis_client = AsyncMock()

        # First 2 attempts fail, 3rd succeeds
        repo.redis_client.set = AsyncMock(side_effect=[False, False, True])
        repo.redis_client.delete = AsyncMock(return_value=1)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            async with repo.stream_lock(stream_id):
                pass

        # Should have retried with backoff
        assert repo.redis_client.set.call_count == 3, "Should retry 3 times"
        assert mock_sleep.call_count == 2, "Should sleep twice (between retries)"

    @pytest.mark.asyncio
    async def test_lock_context_manager_raises_on_max_retries(self):
        """Test that context manager raises RuntimeError after max retries."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-005"

        repo.redis_client = AsyncMock()
        repo.redis_client.set = AsyncMock(return_value=False)  # Always fail

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="Failed to acquire lock"):
                async with repo.stream_lock(stream_id):
                    pass

    @pytest.mark.asyncio
    async def test_lock_context_manager_releases_on_exception(self):
        """Test that lock is released even if exception occurs in context."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-006"

        repo.redis_client = AsyncMock()
        repo.redis_client.set = AsyncMock(return_value=True)
        repo.redis_client.delete = AsyncMock(return_value=1)

        # Exception inside context
        with pytest.raises(ValueError):
            async with repo.stream_lock(stream_id):
                raise ValueError("Test error")

        # Lock should still be released
        repo.redis_client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_lock_timeout_prevents_deadlock(self):
        """Test that lock timeout is set to prevent deadlock on crashes."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-007"

        repo.redis_client = AsyncMock()
        repo.redis_client.set = AsyncMock(return_value=True)

        timeout_seconds = 30
        await repo.acquire_lock(stream_id, timeout_seconds)

        # Verify EX parameter (expiry) was set
        call_kwargs = repo.redis_client.set.call_args[1]
        assert call_kwargs["ex"] == timeout_seconds, "Lock should have expiry set"

    @pytest.mark.asyncio
    async def test_multiple_streams_independent_locks(self):
        """Test that different streams have independent locks."""
        repo = RedisSessionRepository("redis://localhost:6379/0")

        repo.redis_client = AsyncMock()
        repo.redis_client.set = AsyncMock(return_value=True)

        # Acquire locks for two different streams
        await repo.acquire_lock("stream-1")
        await repo.acquire_lock("stream-2")

        # Both should succeed (independent locks)
        assert repo.redis_client.set.call_count == 2
        calls = repo.redis_client.set.call_args_list
        lock_keys = [call[0][0] for call in calls]
        assert "lock:stream-1" in lock_keys
        assert "lock:stream-2" in lock_keys

    @pytest.mark.asyncio
    async def test_lock_key_generation(self):
        """Test lock key naming convention."""
        stream_id = "abc-123"
        lock_key = RedisSessionRepository._get_lock_key(stream_id)
        assert lock_key == "lock:abc-123"

    @pytest.mark.asyncio
    async def test_session_save_with_lock_prevents_race(self):
        """Test that session operations use locks in real workflow."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-008"

        repo.redis_client = AsyncMock()
        repo.redis_client.set = AsyncMock(return_value=True)
        repo.redis_client.setex = AsyncMock()
        repo.redis_client.delete = AsyncMock(return_value=1)

        session = ConversationSession.create(
            stream_identifier=StreamIdentifier(value=stream_id),
            caller_number="+1234567890",
            called_number="+9876543210",
            audio_format=AudioFormat(sample_rate=8000, channels=1, encoding="PCM16LE"),
        )

        # Simulate: acquire lock, modify, save, release
        async with repo.stream_lock(stream_id):
            await repo.save(session)

        # Verify: lock set, session saved, lock deleted
        assert repo.redis_client.set.called, "Lock should be acquired"
        assert repo.redis_client.setex.called, "Session should be saved"
        assert repo.redis_client.delete.called, "Lock should be released"


class TestLockBackoffStrategy:
    """Test exponential backoff retry strategy."""

    @pytest.mark.asyncio
    async def test_backoff_delays_increase_exponentially(self):
        """Test backoff delays: 100ms, 200ms, 400ms, 800ms."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-009"

        repo.redis_client = AsyncMock()
        repo.redis_client.set = AsyncMock(side_effect=[False, False, False, False, True])
        repo.redis_client.delete = AsyncMock(return_value=1)

        sleep_calls = []

        async def mock_sleep(delay):
            sleep_calls.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            async with repo.stream_lock(stream_id):
                pass

        # Expected delays: 100ms, 200ms, 400ms, 800ms
        expected_delays = [0.1, 0.2, 0.4, 0.8]
        assert len(sleep_calls) == 4, f"Expected 4 sleep calls, got {len(sleep_calls)}"
        for actual, expected in zip(sleep_calls, expected_delays):
            assert abs(actual - expected) < 0.001, f"Delay {actual} != {expected}"

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max_delay(self):
        """Test backoff capped at 5 seconds max."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-010"

        repo.redis_client = AsyncMock()
        # Always fail (to trigger all retries)
        repo.redis_client.set = AsyncMock(return_value=False)

        sleep_calls = []

        async def mock_sleep(delay):
            sleep_calls.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            try:
                async with repo.stream_lock(stream_id):
                    pass
            except RuntimeError:
                pass

        # Max delay should never exceed 5 seconds
        assert all(d <= 5.0 for d in sleep_calls), "Delays should be capped at 5 seconds"


class TestLockErrorHandling:
    """Test error handling during lock operations."""

    @pytest.mark.asyncio
    async def test_lock_redis_connection_error_graceful_failure(self):
        """Test graceful failure if Redis unavailable during lock."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-011"

        repo.redis_client = AsyncMock()
        repo.redis_client.set = AsyncMock(side_effect=Exception("Connection refused"))

        acquired = await repo.acquire_lock(stream_id)
        assert not acquired, "Should fail gracefully on Redis error"

    @pytest.mark.asyncio
    async def test_lock_release_redis_error_logged(self):
        """Test error logging if lock release fails."""
        repo = RedisSessionRepository("redis://localhost:6379/0")
        stream_id = "test-stream-012"

        repo.redis_client = AsyncMock()
        repo.redis_client.delete = AsyncMock(side_effect=Exception("Connection lost"))

        # Should not raise, just log
        await repo.release_lock(stream_id)
        # Verify no unhandled exception


# Integration test (requires actual Redis)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_lock_integration_with_real_redis():
    """
    Integration test with real Redis.
    
    Run with: pytest -m integration -k test_lock_integration
    Requires: Redis running on localhost:6379
    """
    repo1 = RedisSessionRepository("redis://localhost:6379/0")
    repo2 = RedisSessionRepository("redis://localhost:6379/0")

    await repo1.connect()
    await repo2.connect()

    try:
        stream_id = "integration-test-stream"

        # repo1 acquires lock
        assert await repo1.acquire_lock(stream_id), "repo1 should acquire lock"

        # repo2 blocked
        assert not await repo2.acquire_lock(stream_id), "repo2 should be blocked"

        # repo1 releases
        await repo1.release_lock(stream_id)

        # Now repo2 can acquire
        assert await repo2.acquire_lock(stream_id), "repo2 should acquire after repo1 release"

        await repo2.release_lock(stream_id)

    finally:
        await repo1.disconnect()
        await repo2.disconnect()
