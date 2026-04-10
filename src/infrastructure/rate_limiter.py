"""Rate limiter using token bucket algorithm.

Supports both IP-level and stream-level rate limiting.
Typical usage:
    limiter = RateLimiter(ip_rate=100, stream_rate=50)
    
    # Check IP rate limit (per second)
    is_allowed = await limiter.check_ip_limit("192.168.1.100")
    
    # Check stream rate limit (per second)
    is_allowed = await limiter.check_stream_limit("stream_123")
"""

import asyncio
import logging
import time
from typing import Dict

logger = logging.getLogger(__name__)


class TokenBucket:
    """Token bucket for rate limiting."""

    def __init__(self, capacity: float, refill_rate: float):
        """
        Initialize token bucket.

        Args:
            capacity: Maximum tokens (bucket size)
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def try_consume(self, count: int = 1) -> bool:
        """
        Try to consume tokens.

        Args:
            count: Number of tokens to consume (default 1)

        Returns:
            True if tokens consumed, False if insufficient tokens
        """
        self._refill()
        if self.tokens >= count:
            self.tokens -= count
            return True
        return False


class RateLimiter:
    """Rate limiter with per-IP and per-stream buckets."""

    def __init__(self, ip_rate: float = 100.0, stream_rate: float = 50.0):
        """
        Initialize rate limiter.

        Args:
            ip_rate: Tokens per second per IP (default 100)
            stream_rate: Tokens per second per stream (default 50)
        """
        self.ip_rate = ip_rate
        self.stream_rate = stream_rate
        self._ip_buckets: Dict[str, TokenBucket] = {}
        self._stream_buckets: Dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()
        logger.info(f"RateLimiter initialized: ip_rate={ip_rate}, stream_rate={stream_rate}")

    async def check_ip_limit(self, client_ip: str) -> bool:
        """
        Check if IP is within rate limit.

        Args:
            client_ip: Client IP address

        Returns:
            True if request allowed, False if rate limit exceeded
        """
        async with self._lock:
            if client_ip not in self._ip_buckets:
                self._ip_buckets[client_ip] = TokenBucket(self.ip_rate, self.ip_rate)

            bucket = self._ip_buckets[client_ip]
            allowed = bucket.try_consume(1)

            if not allowed:
                logger.warning(f"IP rate limit exceeded for {client_ip}")
            return allowed

    async def check_stream_limit(self, stream_id: str) -> bool:
        """
        Check if stream is within rate limit.

        Args:
            stream_id: Stream identifier

        Returns:
            True if request allowed, False if rate limit exceeded
        """
        async with self._lock:
            if stream_id not in self._stream_buckets:
                self._stream_buckets[stream_id] = TokenBucket(self.stream_rate, self.stream_rate)

            bucket = self._stream_buckets[stream_id]
            allowed = bucket.try_consume(1)

            if not allowed:
                logger.warning(f"Stream rate limit exceeded for {stream_id}")
            return allowed

    async def cleanup_stream(self, stream_id: str) -> None:
        """
        Remove stream rate limit bucket (call when stream ends).

        Args:
            stream_id: Stream identifier
        """
        async with self._lock:
            self._stream_buckets.pop(stream_id, None)
