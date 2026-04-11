"""Hierarchical rate limiter with token bucket algorithm.

Supports multi-level rate limiting:
- Per-tenant limits (different tiers: free, pro, enterprise)
- Per-region limits (geographic region constraints)
- Global limit (total calls across all regions)
- IP-level and stream-level limits (backward compatible)

Token bucket algorithm ensures smooth rate control with burst capacity.

Typical usage:
    limiter = HierarchicalRateLimiter(config_path="config/rate-limits.yaml")
    
    # Check tenant-level limit
    allowed, reason = await limiter.check_tenant_limit("tenant_123", "india")
    
    # Check region-level limit
    allowed, reason = await limiter.check_region_limit("india")
    
    # Check global limit
    allowed, reason = await limiter.check_global_limit()
"""

import asyncio
import logging
import time
import yaml
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a level (tenant, region, or global)."""
    calls_per_minute: int
    burst_capacity: int


class TokenBucket:
    """Token bucket for rate limiting with refill mechanism."""

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

    def get_available_tokens(self) -> float:
        """Get current available tokens after refill."""
        self._refill()
        return self.tokens


class HierarchicalRateLimiter:
    """
    Hierarchical rate limiter with per-tenant, per-region, and global limits.
    
    Check order (most restrictive wins):
    1. Tenant-level limit (per-tenant bucket)
    2. Region-level limit (per-region bucket)
    3. Global limit (single global bucket)
    """

    def __init__(self, config_path: str = "config/rate-limits.yaml"):
        """
        Initialize hierarchical rate limiter.

        Args:
            config_path: Path to YAML configuration file
        """
        self.config_path = config_path
        self.config = {}
        self._load_config()
        
        # Token buckets for each level
        self._tenant_buckets: Dict[str, TokenBucket] = {}  # tenant_id -> bucket
        self._region_buckets: Dict[str, TokenBucket] = {}  # region_id -> bucket
        self._global_bucket: Optional[TokenBucket] = None
        self._ip_buckets: Dict[str, TokenBucket] = {}  # IP -> bucket (backward compat)
        self._stream_buckets: Dict[str, TokenBucket] = {}  # stream_id -> bucket (backward compat)
        
        # Metrics tracking
        self._rate_limit_hits: Dict[str, int] = {}  # tenant_id -> hit count
        self._queue_depths: Dict[str, int] = {}  # tenant_id -> queue depth
        self._lock = asyncio.Lock()
        
        logger.info(f"HierarchicalRateLimiter initialized from {config_path}")

    def _load_config(self) -> None:
        """Load and parse YAML configuration."""
        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
            logger.info(f"Loaded rate limit config from {self.config_path}")
        except FileNotFoundError:
            logger.warning(f"Config file {self.config_path} not found, using defaults")
            self.config = self._get_default_config()
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse config: {e}, using defaults")
            self.config = self._get_default_config()

    def _get_default_config(self) -> Dict:
        """Get default configuration."""
        return {
            'global': {'calls_per_minute': 1000, 'burst_capacity': 1200},
            'regions': {
                'india': {'calls_per_minute': 300, 'burst_capacity': 360},
                'us': {'calls_per_minute': 250, 'burst_capacity': 300},
                'eu': {'calls_per_minute': 200, 'burst_capacity': 240},
                'default': {'calls_per_minute': 100, 'burst_capacity': 120},
            },
            'tiers': {
                'free': {'calls_per_minute': 10, 'burst_capacity': 12},
                'pro': {'calls_per_minute': 100, 'burst_capacity': 120},
                'enterprise': {'calls_per_minute': 500, 'burst_capacity': 600},
            },
            'rejection': {
                'enable_fair_queuing': True,
                'queue_max_size': 100,
                'queue_ttl_seconds': 30,
            },
            'monitoring': {
                'collect_metrics': True,
                'alert_threshold_percent': 80,
            }
        }

    def reload_config(self) -> None:
        """Reload configuration from file (hot-reload support)."""
        self._load_config()
        logger.info("Rate limit config reloaded")

    def _get_tenant_limit(self, tenant_id: str, region: str = "default") -> RateLimitConfig:
        """Get rate limit config for a specific tenant."""
        # Check tenant-specific override first
        if 'tenant_overrides' in self.config:
            override = self.config['tenant_overrides'].get(tenant_id)
            if override:
                return RateLimitConfig(
                    calls_per_minute=override['calls_per_minute'],
                    burst_capacity=override['burst_capacity']
                )
        
        # Fall back to tier-based limit
        tier = 'free'  # Default tier
        if 'tiers' in self.config:
            tier_config = self.config['tiers'].get(tier, {})
            return RateLimitConfig(
                calls_per_minute=tier_config.get('calls_per_minute', 10),
                burst_capacity=tier_config.get('burst_capacity', 12)
            )
        
        return RateLimitConfig(calls_per_minute=10, burst_capacity=12)

    def _get_region_limit(self, region: str) -> RateLimitConfig:
        """Get rate limit config for a specific region."""
        if 'regions' in self.config:
            region_config = self.config['regions'].get(region) or \
                          self.config['regions'].get('default', {})
            return RateLimitConfig(
                calls_per_minute=region_config.get('calls_per_minute', 100),
                burst_capacity=region_config.get('burst_capacity', 120)
            )
        return RateLimitConfig(calls_per_minute=100, burst_capacity=120)

    def _get_global_limit(self) -> RateLimitConfig:
        """Get global rate limit config."""
        if 'global' in self.config:
            global_config = self.config['global']
            return RateLimitConfig(
                calls_per_minute=global_config.get('calls_per_minute', 1000),
                burst_capacity=global_config.get('burst_capacity', 1200)
            )
        return RateLimitConfig(calls_per_minute=1000, burst_capacity=1200)

    async def check_tenant_limit(
        self,
        tenant_id: str,
        region: str = "default"
    ) -> Tuple[bool, str]:
        """
        Check if tenant is within rate limit.

        Args:
            tenant_id: Tenant identifier
            region: Geographic region

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        async with self._lock:
            config = self._get_tenant_limit(tenant_id, region)
            refill_rate = config.calls_per_minute / 60.0  # Convert to per-second
            
            if tenant_id not in self._tenant_buckets:
                self._tenant_buckets[tenant_id] = TokenBucket(
                    config.burst_capacity, refill_rate
                )
            
            bucket = self._tenant_buckets[tenant_id]
            allowed = bucket.try_consume(1)
            
            if allowed:
                return True, f"Allowed (tenant {tenant_id})"
            else:
                self._rate_limit_hits[tenant_id] = self._rate_limit_hits.get(tenant_id, 0) + 1
                return False, f"Tenant rate limit exceeded for {tenant_id}"

    async def check_region_limit(self, region: str) -> Tuple[bool, str]:
        """
        Check if region is within rate limit.

        Args:
            region: Geographic region identifier

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        async with self._lock:
            config = self._get_region_limit(region)
            refill_rate = config.calls_per_minute / 60.0
            
            if region not in self._region_buckets:
                self._region_buckets[region] = TokenBucket(
                    config.burst_capacity, refill_rate
                )
            
            bucket = self._region_buckets[region]
            allowed = bucket.try_consume(1)
            
            if allowed:
                return True, f"Allowed (region {region})"
            else:
                return False, f"Region rate limit exceeded for {region}"

    async def check_global_limit(self) -> Tuple[bool, str]:
        """
        Check if global rate limit is not exceeded.

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        async with self._lock:
            if self._global_bucket is None:
                config = self._get_global_limit()
                refill_rate = config.calls_per_minute / 60.0
                self._global_bucket = TokenBucket(config.burst_capacity, refill_rate)
            
            allowed = self._global_bucket.try_consume(1)
            
            if allowed:
                return True, "Allowed (global)"
            else:
                return False, "Global rate limit exceeded"

    async def check_all_limits(
        self,
        tenant_id: str,
        region: str = "default"
    ) -> Tuple[bool, str]:
        """
        Check all three levels: tenant, region, global (hierarchical).

        Args:
            tenant_id: Tenant identifier
            region: Geographic region

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        # Check tenant limit first (most specific)
        allowed, reason = await self.check_tenant_limit(tenant_id, region)
        if not allowed:
            return False, reason
        
        # Check region limit second
        allowed, reason = await self.check_region_limit(region)
        if not allowed:
            return False, reason
        
        # Check global limit last (most general)
        allowed, reason = await self.check_global_limit()
        return allowed, reason

    async def check_ip_limit(self, client_ip: str) -> bool:
        """
        Check if IP is within rate limit (backward compatible).

        Args:
            client_ip: Client IP address

        Returns:
            True if request allowed, False if rate limit exceeded
        """
        async with self._lock:
            ip_rate = 100.0  # Default: 100 requests/sec per IP
            if client_ip not in self._ip_buckets:
                self._ip_buckets[client_ip] = TokenBucket(ip_rate, ip_rate)

            bucket = self._ip_buckets[client_ip]
            allowed = bucket.try_consume(1)

            if not allowed:
                logger.warning(f"IP rate limit exceeded for {client_ip}")
            return allowed

    async def check_stream_limit(self, stream_id: str) -> bool:
        """
        Check if stream is within rate limit (backward compatible).

        Args:
            stream_id: Stream identifier

        Returns:
            True if request allowed, False if rate limit exceeded
        """
        async with self._lock:
            stream_rate = 50.0  # Default: 50 requests/sec per stream
            if stream_id not in self._stream_buckets:
                self._stream_buckets[stream_id] = TokenBucket(stream_rate, stream_rate)

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

    async def get_metrics(self, tenant_id: Optional[str] = None) -> Dict:
        """
        Get rate limiting metrics.

        Args:
            tenant_id: Optional tenant to get metrics for

        Returns:
            Dict with rate limit metrics
        """
        async with self._lock:
            if tenant_id:
                bucket = self._tenant_buckets.get(tenant_id)
                if bucket:
                    return {
                        'tenant_id': tenant_id,
                        'available_tokens': bucket.get_available_tokens(),
                        'rate_limit_hits': self._rate_limit_hits.get(tenant_id, 0),
                        'queue_depth': self._queue_depths.get(tenant_id, 0),
                    }
                return {'tenant_id': tenant_id, 'not_found': True}
            
            # Return global metrics
            global_tokens = 0
            if self._global_bucket:
                global_tokens = self._global_bucket.get_available_tokens()
            
            return {
                'global_available_tokens': global_tokens,
                'total_rate_limit_hits': sum(self._rate_limit_hits.values()),
                'rate_limit_hits_by_tenant': self._rate_limit_hits.copy(),
                'queue_depths_by_tenant': self._queue_depths.copy(),
            }


# ── Backward Compatibility ─────────────────────────────────────────────────────
# Alias for backward compatibility with existing code that imports RateLimiter
RateLimiter = HierarchicalRateLimiter
