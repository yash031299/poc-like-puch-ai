"""Tests for RateLimiter."""

import asyncio
import pytest
import time

from src.infrastructure.rate_limiter import RateLimiter, TokenBucket


class TestTokenBucket:
    """Tests for TokenBucket class."""

    def test_token_bucket_init(self):
        """TokenBucket initializes with correct capacity."""
        bucket = TokenBucket(capacity=100, refill_rate=10)
        assert bucket.capacity == 100
        assert bucket.refill_rate == 10
        assert bucket.tokens == 100

    def test_token_bucket_consume_success(self):
        """TokenBucket allows consume when tokens available."""
        bucket = TokenBucket(capacity=10, refill_rate=1)
        assert bucket.try_consume(1) is True
        assert bucket.tokens == 9

    def test_token_bucket_consume_multiple(self):
        """TokenBucket consumes multiple tokens at once."""
        bucket = TokenBucket(capacity=10, refill_rate=1)
        assert bucket.try_consume(5) is True
        assert bucket.tokens == 5

    def test_token_bucket_consume_failure(self):
        """TokenBucket rejects consume when insufficient tokens."""
        bucket = TokenBucket(capacity=10, refill_rate=0)  # No refill
        bucket.tokens = 0
        assert bucket.try_consume(1) is False
        assert bucket.tokens == 0

    def test_token_bucket_refill(self):
        """TokenBucket refills over time."""
        bucket = TokenBucket(capacity=100, refill_rate=10)
        bucket.tokens = 0
        time.sleep(0.1)  # Wait 100ms
        bucket._refill()
        assert bucket.tokens >= 1  # At least 1 token refilled

    def test_token_bucket_refill_capped_at_capacity(self):
        """TokenBucket refill does not exceed capacity."""
        bucket = TokenBucket(capacity=10, refill_rate=100)
        bucket.tokens = 5
        time.sleep(0.1)
        bucket._refill()
        assert bucket.tokens <= 10  # Capped at capacity


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.mark.asyncio
    async def test_rate_limiter_init(self):
        """RateLimiter initializes with correct rates."""
        limiter = RateLimiter(ip_rate=100, stream_rate=50)
        assert limiter.ip_rate == 100
        assert limiter.stream_rate == 50

    @pytest.mark.asyncio
    async def test_ip_rate_limit_allowed(self):
        """IP rate limit allows requests within limit."""
        limiter = RateLimiter(ip_rate=10)
        # Should allow up to 10 requests
        for _ in range(10):
            assert await limiter.check_ip_limit("192.168.1.1") is True

    @pytest.mark.asyncio
    async def test_ip_rate_limit_exceeded(self):
        """IP rate limit rejects when exceeded."""
        limiter = RateLimiter(ip_rate=5)
        # Consume all tokens
        for _ in range(5):
            assert await limiter.check_ip_limit("192.168.1.1") is True
        # Next request should be rejected
        assert await limiter.check_ip_limit("192.168.1.1") is False

    @pytest.mark.asyncio
    async def test_ip_rate_limit_per_ip(self):
        """IP rate limit is tracked per IP."""
        limiter = RateLimiter(ip_rate=5)
        # IP1 uses all tokens
        for _ in range(5):
            assert await limiter.check_ip_limit("192.168.1.1") is True
        # IP1 is rate limited
        assert await limiter.check_ip_limit("192.168.1.1") is False
        # IP2 should still have tokens
        assert await limiter.check_ip_limit("192.168.1.2") is True

    @pytest.mark.asyncio
    async def test_stream_rate_limit_allowed(self):
        """Stream rate limit allows requests within limit."""
        limiter = RateLimiter(stream_rate=10)
        # Should allow up to 10 requests
        for _ in range(10):
            assert await limiter.check_stream_limit("stream_1") is True

    @pytest.mark.asyncio
    async def test_stream_rate_limit_exceeded(self):
        """Stream rate limit rejects when exceeded."""
        limiter = RateLimiter(stream_rate=5)
        # Consume all tokens
        for _ in range(5):
            assert await limiter.check_stream_limit("stream_1") is True
        # Next request should be rejected
        assert await limiter.check_stream_limit("stream_1") is False

    @pytest.mark.asyncio
    async def test_stream_rate_limit_per_stream(self):
        """Stream rate limit is tracked per stream."""
        limiter = RateLimiter(stream_rate=5)
        # stream_1 uses all tokens
        for _ in range(5):
            assert await limiter.check_stream_limit("stream_1") is True
        # stream_1 is rate limited
        assert await limiter.check_stream_limit("stream_1") is False
        # stream_2 should still have tokens
        assert await limiter.check_stream_limit("stream_2") is True

    @pytest.mark.asyncio
    async def test_cleanup_stream(self):
        """Cleanup removes stream bucket."""
        limiter = RateLimiter(stream_rate=5)
        # Use stream
        await limiter.check_stream_limit("stream_1")
        assert "stream_1" in limiter._stream_buckets
        # Cleanup
        await limiter.cleanup_stream("stream_1")
        assert "stream_1" not in limiter._stream_buckets

    @pytest.mark.asyncio
    async def test_token_refill_over_time(self):
        """Tokens refill over time, allowing more requests."""
        limiter = RateLimiter(ip_rate=10)
        ip = "192.168.1.1"
        # Use all tokens
        for _ in range(10):
            assert await limiter.check_ip_limit(ip) is True
        # Should be rate limited
        assert await limiter.check_ip_limit(ip) is False
        # Wait for tokens to refill
        await asyncio.sleep(0.15)
        # Should allow more requests
        assert await limiter.check_ip_limit(ip) is True

    @pytest.mark.asyncio
    async def test_concurrent_ip_requests(self):
        """RateLimiter handles concurrent requests safely."""
        limiter = RateLimiter(ip_rate=10)
        ip = "192.168.1.1"

        async def check_limit():
            return await limiter.check_ip_limit(ip)

        # 20 concurrent requests (should allow first 10)
        results = await asyncio.gather(*[check_limit() for _ in range(20)])
        assert sum(results) == 10  # Exactly 10 should succeed

    @pytest.mark.asyncio
    async def test_concurrent_stream_requests(self):
        """RateLimiter handles concurrent stream requests safely."""
        limiter = RateLimiter(stream_rate=10)
        stream = "stream_1"

        async def check_limit():
            return await limiter.check_stream_limit(stream)

        # 20 concurrent requests (should allow first 10)
        results = await asyncio.gather(*[check_limit() for _ in range(20)])
        assert sum(results) == 10  # Exactly 10 should succeed
