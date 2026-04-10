"""RedisSessionRepository — Redis-backed session persistence for production.

Enables "reconnect and resume" by storing ConversationSession state in Redis
with automatic TTL expiration (12 hours per session).

Distributed Locking (Phase 2C):
- Prevents race conditions when multiple instances handle the same stream
- Uses Redis SET with NX (set-if-not-exists) and EX (expiry) for atomic locks
- 30-second lock timeout prevents deadlock on instance crashes
- Exponential backoff retry on lock contention

Usage:
    redis_repo = RedisSessionRepository(redis_url="redis://localhost:6379/0")
    await redis_repo.connect()
    
    # Stateless read (no lock needed)
    session = await redis_repo.get(stream_id)
    
    # State-modifying operation (acquires lock for atomicity)
    async with redis_repo.acquire_lock(stream_id):
        session = await redis_repo.get(stream_id)
        # ... modify session ...
        await redis_repo.save(session)
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional
import redis.asyncio as redis

from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.domain.value_objects.audio_format import AudioFormat
from src.domain.entities.utterance import Utterance
from src.domain.entities.ai_response import AIResponse
from src.ports.session_repository_port import SessionRepositoryPort

logger = logging.getLogger(__name__)

# Lock configuration
LOCK_TIMEOUT_SECONDS = 30  # Lock TTL (prevents deadlock on crash)
LOCK_RETRY_MAX_ATTEMPTS = 5  # Max retries before giving up
LOCK_RETRY_BASE_DELAY_MS = 100  # Initial backoff delay (ms)
LOCK_RETRY_MAX_DELAY_MS = 5000  # Max backoff delay (ms)


class RedisSessionRepository(SessionRepositoryPort):
    """
    Redis-backed implementation of SessionRepositoryPort.

    Persists ConversationSession to Redis with:
    - JSON serialization for storage
    - Automatic TTL expiration (12 hours)
    - Connection pooling for efficiency
    - Distributed locking for multi-instance safety
    - Graceful degradation on connection errors

    For production:
    - Use ElastiCache (AWS) or similar managed service
    - Enable AOF persistence for durability
    - Configure password auth and TLS
    
    Distributed Locking:
    - Prevents concurrent access to same stream from multiple instances
    - Lock is acquired atomically via Redis SET NX EX
    - Lock expires automatically (30s) to handle instance crashes
    - Exponential backoff on contention
    """

    SESSION_TTL_SECONDS = 12 * 3600  # 12 hours
    SESSION_KEY_PREFIX = "session"
    LOCK_KEY_PREFIX = "lock"

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """
        Initialize Redis session repository.

        Args:
            redis_url: Redis connection URL (default: localhost)
        """
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """
        Establish connection to Redis.

        Should be called during application startup (lifespan).
        """
        try:
            self.redis_client = await redis.from_url(
                self.redis_url,
                decode_responses=True,
                max_connections=50,
            )
            # Test connection
            await self.redis_client.ping()
            logger.info("✅ Redis connected: %s", self.redis_url)
        except Exception as e:
            logger.error("❌ Redis connection failed: %s", e)
            raise

    async def disconnect(self) -> None:
        """
        Close Redis connection.

        Should be called during application shutdown (lifespan).
        """
        if self.redis_client:
            await self.redis_client.close()
            logger.info("✅ Redis disconnected")

    async def save(self, session: ConversationSession) -> None:
        """
        Persist or update a ConversationSession in Redis.

        Key format: session:{stream_id}
        Value: JSON serialized ConversationSession
        TTL: 12 hours (resets on each save)

        Args:
            session: ConversationSession to save

        Raises:
            ConnectionError: If Redis is unavailable
        """
        if not self.redis_client:
            logger.warning("⚠️ Redis not connected, skipping save")
            return

        try:
            key = self._get_session_key(session.stream_id)
            value = self._serialize_session(session)

            await self.redis_client.setex(
                key,
                self.SESSION_TTL_SECONDS,
                value
            )
            logger.debug(f"✅ Session saved: {key} (TTL: {self.SESSION_TTL_SECONDS}s)")
        except Exception as e:
            logger.error(f"❌ Failed to save session {session.stream_id}: {e}")
            raise

    async def get(self, stream_id: str) -> Optional[ConversationSession]:
        """
        Retrieve a ConversationSession from Redis.

        Key format: session:{stream_id}

        Args:
            stream_id: Stream identifier

        Returns:
            ConversationSession if found, None otherwise

        Raises:
            ConnectionError: If Redis is unavailable
        """
        if not self.redis_client:
            logger.warning("⚠️ Redis not connected, returning None")
            return None

        try:
            key = self._get_session_key(stream_id)
            value = await self.redis_client.get(key)

            if value is None:
                logger.debug(f"⚠️ Session not found in Redis: {key}")
                return None

            session = self._deserialize_session(value)
            logger.debug(f"✅ Session retrieved: {key}")
            return session
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to deserialize session {stream_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Failed to retrieve session {stream_id}: {e}")
            raise

    async def delete(self, stream_id: str) -> None:
        """
        Remove a ConversationSession from Redis.

        Called when a call ends (EndCallUseCase).

        Args:
            stream_id: Stream identifier

        Raises:
            ConnectionError: If Redis is unavailable
        """
        if not self.redis_client:
            logger.warning("⚠️ Redis not connected, skipping delete")
            return

        try:
            key = self._get_session_key(stream_id)
            await self.redis_client.delete(key)
            logger.debug(f"✅ Session deleted: {key}")
        except Exception as e:
            logger.error(f"❌ Failed to delete session {stream_id}: {e}")
            raise

    async def acquire_lock(self, stream_id: str, timeout_seconds: int = LOCK_TIMEOUT_SECONDS) -> bool:
        """
        Acquire distributed lock for a stream.

        Uses Redis SET with NX (set-if-not-exists) and EX (expiry).
        This implements a simple spinlock for single-key mutual exclusion.

        Args:
            stream_id: Stream identifier to lock
            timeout_seconds: Lock TTL in seconds (auto-expires on crash)

        Returns:
            True if lock acquired, False if already locked by another instance
        """
        if not self.redis_client:
            logger.warning("⚠️ Redis not connected, cannot acquire lock")
            return False

        lock_key = self._get_lock_key(stream_id)
        lock_value = f"{int(time.time())}-{id(self)}"  # Unique value per instance

        try:
            acquired = await self.redis_client.set(
                lock_key,
                lock_value,
                nx=True,  # Only set if key doesn't exist (exclusive lock)
                ex=timeout_seconds,  # Auto-expire after timeout
            )
            if acquired:
                logger.debug(f"🔒 Lock acquired for stream {stream_id[:8]}")
            else:
                logger.debug(f"⏳ Lock held by another instance for stream {stream_id[:8]}")
            return bool(acquired)
        except Exception as e:
            logger.error(f"❌ Error acquiring lock for {stream_id[:8]}: {e}")
            return False

    async def release_lock(self, stream_id: str) -> None:
        """
        Release distributed lock for a stream.

        Called at end of critical section (typically from EndCallUseCase).

        Args:
            stream_id: Stream identifier to unlock
        """
        if not self.redis_client:
            return

        lock_key = self._get_lock_key(stream_id)
        try:
            deleted = await self.redis_client.delete(lock_key)
            if deleted:
                logger.debug(f"🔓 Lock released for stream {stream_id[:8]}")
        except Exception as e:
            logger.error(f"❌ Error releasing lock for {stream_id[:8]}: {e}")

    @asynccontextmanager
    async def stream_lock(self, stream_id: str, timeout_seconds: int = LOCK_TIMEOUT_SECONDS):
        """
        Context manager for distributed locking with exponential backoff.

        Acquires lock on entry, releases on exit.
        Retries with exponential backoff on contention.

        Example:
            async with repo.stream_lock(stream_id):
                # Critical section: safe from concurrent access
                session = await repo.get(stream_id)
                # ... modify session ...
                await repo.save(session)

        Args:
            stream_id: Stream identifier to lock
            timeout_seconds: Lock timeout

        Raises:
            RuntimeError: If lock cannot be acquired after max retries
        """
        acquired = False
        attempt = 0

        # Exponential backoff retry loop
        while attempt < LOCK_RETRY_MAX_ATTEMPTS:
            if await self.acquire_lock(stream_id, timeout_seconds):
                acquired = True
                break

            attempt += 1
            if attempt < LOCK_RETRY_MAX_ATTEMPTS:
                # Exponential backoff: 100ms, 200ms, 400ms, 800ms, 1600ms
                delay_ms = min(
                    LOCK_RETRY_BASE_DELAY_MS * (2 ** (attempt - 1)),
                    LOCK_RETRY_MAX_DELAY_MS,
                )
                logger.debug(
                    f"Retrying lock for {stream_id[:8]} "
                    f"(attempt {attempt}/{LOCK_RETRY_MAX_ATTEMPTS}, backoff {delay_ms}ms)"
                )
                await asyncio.sleep(delay_ms / 1000.0)

        if not acquired:
            raise RuntimeError(
                f"Failed to acquire lock for stream {stream_id} "
                f"after {LOCK_RETRY_MAX_ATTEMPTS} attempts"
            )

        try:
            yield
        finally:
            await self.release_lock(stream_id)

    @staticmethod
    def _get_lock_key(stream_id: str) -> str:
        """
        Generate Redis key for a session lock.

        Args:
            stream_id: Stream identifier

        Returns:
            Redis lock key in format "lock:{stream_id}"
        """
        return f"{RedisSessionRepository.LOCK_KEY_PREFIX}:{stream_id}"

    @staticmethod
    def _get_session_key(stream_id: str) -> str:
        """
        Generate Redis key for a session.

        Args:
            stream_id: Stream identifier

        Returns:
            Redis key in format "session:{stream_id}"
        """
        return f"{RedisSessionRepository.SESSION_KEY_PREFIX}:{stream_id}"

    @staticmethod
    def _serialize_session(session: ConversationSession) -> str:
        """
        Serialize ConversationSession to JSON.

        Captures all session state:
        - Call metadata (caller, called, format)
        - Utterances (text, confidence, is_final, timestamp)
        - AI responses (utterance_id, text, state, timestamp)
        - Interaction state

        Args:
            session: ConversationSession to serialize

        Returns:
            JSON string representation
        """
        return json.dumps({
            "stream_id": session.stream_id,
            "caller_number": session.caller_number,
            "called_number": session.called_number,
            "is_active": session.is_active,
            "is_ended": session.is_ended,
            "audio_format": {
                "sample_rate": session.call_session.audio_format.sample_rate,
                "channels": session.call_session.audio_format.channels,
                "encoding": session.call_session.audio_format.encoding,
            },
            "custom_parameters": session.call_session.custom_parameters or {},
            "utterances": [
                {
                    "utterance_id": u.utterance_id,
                    "text": u.text,
                    "confidence": u.confidence,
                    "is_final": u.is_final,
                    "timestamp": u.timestamp.isoformat() if hasattr(u.timestamp, 'isoformat') else str(u.timestamp),
                }
                for u in session.utterances
            ],
            "ai_responses": [
                {
                    "response_id": r.response_id,
                    "utterance_id": r.utterance_id,
                    "text": r.text,
                    "state": r.state,
                    "timestamp": r.timestamp.isoformat() if hasattr(r.timestamp, 'isoformat') else str(r.timestamp),
                }
                for r in session.ai_responses
            ],
            "interaction_state": session._interaction_state,
        }, default=str)

    @staticmethod
    def _deserialize_session(json_str: str) -> ConversationSession:
        """
        Deserialize JSON back to ConversationSession.

        Restores all session state from JSON representation.

        Args:
            json_str: JSON string from Redis

        Returns:
            Reconstructed ConversationSession

        Raises:
            json.JSONDecodeError: If JSON is invalid
        """
        from datetime import datetime
        
        data = json.loads(json_str)

        stream_id = StreamIdentifier(value=data["stream_id"])
        audio_format = AudioFormat(
            sample_rate=data["audio_format"]["sample_rate"],
            channels=data["audio_format"]["channels"],
            encoding=data["audio_format"]["encoding"],
        )

        # Recreate session
        session = ConversationSession.create(
            stream_identifier=stream_id,
            caller_number=data["caller_number"],
            called_number=data["called_number"],
            audio_format=audio_format,
            custom_parameters=data.get("custom_parameters"),
        )

        # Restore utterances
        for u_data in data.get("utterances", []):
            # Parse timestamp
            ts = u_data.get("timestamp")
            if isinstance(ts, str):
                try:
                    timestamp = datetime.fromisoformat(ts)
                except (ValueError, AttributeError):
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()
            
            utterance = Utterance(
                text=u_data["text"],
                confidence=u_data["confidence"],
                is_final=u_data.get("is_final", True),
                timestamp=timestamp,
            )
            session.add_utterance(utterance)

        # Restore AI responses
        for r_data in data.get("ai_responses", []):
            # Parse timestamp
            ts = r_data.get("timestamp")
            if isinstance(ts, str):
                try:
                    timestamp = datetime.fromisoformat(ts)
                except (ValueError, AttributeError):
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()
            
            ai_response = AIResponse(
                utterance_id=r_data["utterance_id"],
                timestamp=timestamp,
            )
            # Restore the text and state
            if r_data.get("text"):
                ai_response._text = r_data["text"]
            if r_data.get("state"):
                ai_response._state = r_data["state"]
            
            session.add_ai_response(ai_response)

        # Restore interaction state
        session._interaction_state = data.get("interaction_state", "listening")

        return session

    async def health_check(self) -> bool:
        """
        Health check for Redis connection.

        Returns:
            True if Redis is reachable, False otherwise
        """
        if not self.redis_client:
            return False

        try:
            await self.redis_client.ping()
            return True
        except Exception:
            return False

    async def get_active_session_count(self) -> int:
        """
        Count active sessions in Redis.

        Returns:
            Number of sessions with session:* keys
        """
        if not self.redis_client:
            return 0

        try:
            pattern = f"{self.SESSION_KEY_PREFIX}:*"
            count = 0
            async for _ in self.redis_client.scan_iter(match=pattern):
                count += 1
            return count
        except Exception as e:
            logger.error(f"Failed to count sessions: {e}")
            return 0
