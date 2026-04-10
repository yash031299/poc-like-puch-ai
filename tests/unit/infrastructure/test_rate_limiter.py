"""Tests for Hierarchical RateLimiter."""

import asyncio
import pytest
import time
import tempfile
import os
from pathlib import Path

from src.infrastructure.rate_limiter import (
    HierarchicalRateLimiter,
    TokenBucket,
    RateLimitConfig,
)


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

    def test_token_bucket_get_available_tokens(self):
        """TokenBucket.get_available_tokens() returns current tokens."""
        bucket = TokenBucket(capacity=100, refill_rate=10)
        bucket.tokens = 50
        available = bucket.get_available_tokens()
        assert available >= 50


class TestHierarchicalRateLimiter:
    """Tests for HierarchicalRateLimiter class."""

    @pytest.fixture
    def config_file(self):
        """Create a temporary config file."""
        config_content = """
global:
  calls_per_minute: 1000
  burst_capacity: 1200

regions:
  india:
    calls_per_minute: 300
    burst_capacity: 360
  us:
    calls_per_minute: 250
    burst_capacity: 300
  default:
    calls_per_minute: 100
    burst_capacity: 120

tiers:
  free:
    calls_per_minute: 10
    burst_capacity: 12
  pro:
    calls_per_minute: 100
    burst_capacity: 120
  enterprise:
    calls_per_minute: 500
    burst_capacity: 600

tenant_overrides:
  tenant_123:
    calls_per_minute: 150
    burst_capacity: 180
  tenant_456:
    calls_per_minute: 1000
    burst_capacity: 1200

rejection:
  enable_fair_queuing: true
  queue_max_size: 100
  queue_ttl_seconds: 30

monitoring:
  collect_metrics: true
  alert_threshold_percent: 80
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(config_content)
            temp_path = f.name
        yield temp_path
        os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_limiter_init(self, config_file):
        """HierarchicalRateLimiter initializes correctly."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        assert limiter.config is not None
        assert 'global' in limiter.config

    @pytest.mark.asyncio
    async def test_limiter_default_config(self):
        """HierarchicalRateLimiter uses defaults if config file missing."""
        limiter = HierarchicalRateLimiter(config_path="/nonexistent/path.yaml")
        assert limiter.config is not None
        assert 'global' in limiter.config

    @pytest.mark.asyncio
    async def test_tenant_limit_allowed(self, config_file):
        """Tenant limit allows requests within limit."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        # Tenant 123 has 150 calls/min = 2.5 calls/sec, burst 180
        # Should allow burst capacity
        allowed, reason = await limiter.check_tenant_limit("tenant_123", "india")
        assert allowed is True
        assert "tenant_123" in reason

    @pytest.mark.asyncio
    async def test_tenant_limit_exceeded(self, config_file):
        """Tenant limit rejects when exceeded."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        tenant = "tenant_new"
        # Free tier has 10 calls/min = 0.167 calls/sec, burst 12
        for _ in range(12):
            allowed, _ = await limiter.check_tenant_limit(tenant, "india")
            assert allowed is True
        # Next request should fail
        allowed, reason = await limiter.check_tenant_limit(tenant, "india")
        assert allowed is False
        assert "exceeded" in reason.lower()

    @pytest.mark.asyncio
    async def test_region_limit_allowed(self, config_file):
        """Region limit allows requests within limit."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        allowed, reason = await limiter.check_region_limit("india")
        assert allowed is True
        assert "india" in reason

    @pytest.mark.asyncio
    async def test_region_limit_exceeded(self, config_file):
        """Region limit rejects when exceeded."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        # India has 300 calls/min = 5 calls/sec, burst 360
        for _ in range(360):
            allowed, _ = await limiter.check_region_limit("india")
            if not allowed:
                break
        # After burst capacity, should be rejected
        allowed, _ = await limiter.check_region_limit("india")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_global_limit_allowed(self, config_file):
        """Global limit allows requests within limit."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        allowed, reason = await limiter.check_global_limit()
        assert allowed is True
        assert "global" in reason

    @pytest.mark.asyncio
    async def test_global_limit_exceeded(self, config_file):
        """Global limit rejects when exceeded."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        # Global has 1000 calls/min, burst 1200
        for _ in range(1200):
            allowed, _ = await limiter.check_global_limit()
            if not allowed:
                break
        # After burst capacity, should be rejected
        allowed, _ = await limiter.check_global_limit()
        assert allowed is False

    @pytest.mark.asyncio
    async def test_check_all_limits_allowed(self, config_file):
        """check_all_limits allows when all checks pass."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        allowed, reason = await limiter.check_all_limits("tenant_123", "india")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_check_all_limits_tenant_failed(self, config_file):
        """check_all_limits fails if tenant limit exceeded."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        tenant = "test_tenant"
        # Exhaust tenant limit (free tier: burst 12)
        for _ in range(12):
            await limiter.check_tenant_limit(tenant, "india")
        # Next call should fail at tenant level
        allowed, reason = await limiter.check_all_limits(tenant, "india")
        assert allowed is False
        assert "tenant" in reason.lower()

    @pytest.mark.asyncio
    async def test_hierarchical_order(self, config_file):
        """Limits are checked in hierarchical order: tenant -> region -> global."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        
        # Get the bucket to inspect its tokens
        allowed1, _ = await limiter.check_all_limits("tenant_123", "india")
        assert allowed1 is True
        
        # Verify buckets were created for all levels
        assert "tenant_123" in limiter._tenant_buckets
        assert "india" in limiter._region_buckets
        assert limiter._global_bucket is not None

    @pytest.mark.asyncio
    async def test_tenant_override(self, config_file):
        """Tenant overrides take precedence over tier defaults."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        # tenant_456 has custom limit of 1000 calls/min
        config = limiter._get_tenant_limit("tenant_456")
        assert config.calls_per_minute == 1000

    @pytest.mark.asyncio
    async def test_region_default_fallback(self, config_file):
        """Missing region falls back to default."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        config = limiter._get_region_limit("unknown_region")
        # Should fall back to default
        assert config.calls_per_minute == 100

    @pytest.mark.asyncio
    async def test_reload_config(self, config_file):
        """Config can be reloaded without restart."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        original_global = limiter.config['global']['calls_per_minute']
        
        # Modify config file
        with open(config_file, 'r') as f:
            content = f.read()
        content = content.replace(f"calls_per_minute: {original_global}", "calls_per_minute: 500")
        with open(config_file, 'w') as f:
            f.write(content)
        
        # Reload
        limiter.reload_config()
        assert limiter.config['global']['calls_per_minute'] == 500

    @pytest.mark.asyncio
    async def test_backward_compat_ip_limit(self, config_file):
        """Backward compatible IP rate limiting still works."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        ip = "192.168.1.100"
        # Should allow 100 requests/sec per IP
        allowed = await limiter.check_ip_limit(ip)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_backward_compat_stream_limit(self, config_file):
        """Backward compatible stream rate limiting still works."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        stream = "stream_123"
        # Should allow 50 requests/sec per stream
        allowed = await limiter.check_stream_limit(stream)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_cleanup_stream(self, config_file):
        """cleanup_stream removes stream bucket."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        stream = "stream_123"
        await limiter.check_stream_limit(stream)
        assert stream in limiter._stream_buckets
        await limiter.cleanup_stream(stream)
        assert stream not in limiter._stream_buckets

    @pytest.mark.asyncio
    async def test_get_metrics_tenant(self, config_file):
        """get_metrics returns tenant-level metrics."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        tenant = "tenant_test"
        await limiter.check_tenant_limit(tenant, "india")
        metrics = await limiter.get_metrics(tenant)
        assert metrics['tenant_id'] == tenant
        assert 'available_tokens' in metrics

    @pytest.mark.asyncio
    async def test_get_metrics_global(self, config_file):
        """get_metrics returns global metrics."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        await limiter.check_global_limit()
        metrics = await limiter.get_metrics()
        assert 'global_available_tokens' in metrics
        assert 'total_rate_limit_hits' in metrics

    @pytest.mark.asyncio
    async def test_concurrent_tenant_requests(self, config_file):
        """Concurrent requests to same tenant are handled safely."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        tenant = "concurrent_test"
        
        async def check():
            return await limiter.check_tenant_limit(tenant, "india")
        
        # 20 concurrent requests to free tier (burst 12)
        results = await asyncio.gather(*[check() for _ in range(20)])
        allowed_count = sum(1 for allowed, _ in results if allowed)
        # Should allow up to burst capacity
        assert allowed_count <= 12

    @pytest.mark.asyncio
    async def test_concurrent_region_requests(self, config_file):
        """Concurrent region requests are handled safely."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        
        async def check():
            return await limiter.check_region_limit("us")
        
        # 10 concurrent requests to US (burst 300)
        results = await asyncio.gather(*[check() for _ in range(10)])
        allowed_count = sum(1 for allowed, _ in results if allowed)
        assert allowed_count == 10  # All should pass

    @pytest.mark.asyncio
    async def test_concurrent_global_requests(self, config_file):
        """Concurrent global requests are handled safely."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        
        async def check():
            return await limiter.check_global_limit()
        
        # 10 concurrent requests (burst 1200)
        results = await asyncio.gather(*[check() for _ in range(10)])
        allowed_count = sum(1 for allowed, _ in results if allowed)
        assert allowed_count == 10  # All should pass

    @pytest.mark.asyncio
    async def test_rate_limit_hit_tracking(self, config_file):
        """Rate limit hits are tracked per tenant."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        tenant = "tracking_test"
        
        # Exhaust limit
        for _ in range(12):
            await limiter.check_tenant_limit(tenant, "india")
        
        # Cause hits
        await limiter.check_tenant_limit(tenant, "india")
        await limiter.check_tenant_limit(tenant, "india")
        
        metrics = await limiter.get_metrics(tenant)
        assert metrics.get('rate_limit_hits', 0) >= 1

    @pytest.mark.asyncio
    async def test_burst_capacity(self, config_file):
        """Token bucket respects burst capacity."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        tenant = "burst_test"
        
        # Free tier has burst 12
        for i in range(12):
            allowed, _ = await limiter.check_tenant_limit(tenant, "india")
            assert allowed is True
        
        # 13th request should fail
        allowed, _ = await limiter.check_tenant_limit(tenant, "india")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_token_refill_over_time(self, config_file):
        """Tokens refill over time for rate limited tenants."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        tenant = "refill_test"
        
        # Exhaust burst (free tier: 12)
        for _ in range(12):
            await limiter.check_tenant_limit(tenant, "india")
        
        # Should be rate limited
        allowed, _ = await limiter.check_tenant_limit(tenant, "india")
        assert allowed is False
        
        # Wait for refill (free tier: 10 calls/min = ~0.167 calls/sec)
        # At 60 seconds, we'd get 10 refills, so less than 1 second for 1 refill
        await asyncio.sleep(6)  # Wait 6 seconds for ~1 token refill
        
        # Should allow at least one more request
        allowed, _ = await limiter.check_tenant_limit(tenant, "india")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_multiple_tenants_independent(self, config_file):
        """Multiple tenants have independent rate limits."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        
        # Exhaust tenant1
        for _ in range(12):
            await limiter.check_tenant_limit("tenant1", "india")
        
        # tenant1 should be rate limited
        allowed, _ = await limiter.check_tenant_limit("tenant1", "india")
        assert allowed is False
        
        # tenant2 should still have tokens
        allowed, _ = await limiter.check_tenant_limit("tenant2", "india")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_multiple_regions_independent(self, config_file):
        """Multiple regions have independent rate limits."""
        limiter = HierarchicalRateLimiter(config_path=config_file)
        
        # Exhaust US region (burst 300)
        for _ in range(300):
            allowed, _ = await limiter.check_region_limit("us")
            if not allowed:
                break
        
        # US should be rate limited
        allowed, _ = await limiter.check_region_limit("us")
        assert allowed is False
        
        # India should still have tokens
        allowed, _ = await limiter.check_region_limit("india")
        assert allowed is True

