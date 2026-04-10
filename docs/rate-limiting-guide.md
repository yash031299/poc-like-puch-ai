# Advanced Hierarchical Rate Limiting Guide

## Overview

The Exotel AgentStream voice AI PoC implements a **hierarchical rate limiting system** using the token bucket algorithm. This ensures fair resource distribution across tenants, regions, and global deployments.

### Three-Level Hierarchy

Rate limits are checked in order from most specific to most general:

1. **Tenant-Level**: Per-customer limits (free/pro/enterprise tiers or custom overrides)
2. **Region-Level**: Geographic region constraints (India, US, EU, etc.)
3. **Global-Level**: Total capacity across all regions

The request is allowed only if it passes **all three checks**.

## Architecture

### Token Bucket Algorithm

Each rate limit level maintains a token bucket:

- **Capacity**: Burst allowance (e.g., 120 tokens for burst of 20% above sustained rate)
- **Refill Rate**: Tokens per second (e.g., 10 calls/minute = 0.167 tokens/second)
- **Consumption**: Each request consumes 1 token
- **Refill**: Tokens automatically replenish at the refill rate

```
Tokens available: min(capacity, current_tokens + elapsed_seconds * refill_rate)
Request allowed: tokens >= 1
```

### Performance

- **Check Time**: O(1) with async/await safety
- **Concurrency**: Thread-safe with asyncio.Lock
- **Memory**: ~1KB per tenant/region bucket
- **Latency**: <1ms per rate limit check

## Configuration

### Configuration File: `config/rate-limits.yaml`

```yaml
# Global limit (total calls/minute across all regions)
global:
  calls_per_minute: 1000
  burst_capacity: 1200  # 20% burst allowance

# Per-region limits
regions:
  india:
    calls_per_minute: 300
    burst_capacity: 360
  us:
    calls_per_minute: 250
    burst_capacity: 300
  eu:
    calls_per_minute: 200
    burst_capacity: 240
  default:
    calls_per_minute: 100
    burst_capacity: 120

# Tenant tiers
tiers:
  free:
    calls_per_minute: 10
    burst_capacity: 12
    max_concurrent_calls: 2
  pro:
    calls_per_minute: 100
    burst_capacity: 120
    max_concurrent_calls: 20
  enterprise:
    calls_per_minute: 500
    burst_capacity: 600
    max_concurrent_calls: 100

# Tenant-specific overrides
tenant_overrides:
  acme_corp:
    tier: pro
    calls_per_minute: 200  # Override pro tier
    burst_capacity: 240
    region: india
```

### Hot-Reload Configuration

Configuration changes take effect immediately without restarting:

```python
limiter = HierarchicalRateLimiter()
# Update config/rate-limits.yaml
limiter.reload_config()  # Pick up changes
```

## Usage

### Initialization

```python
from src.infrastructure.rate_limiter import HierarchicalRateLimiter

# Load from YAML config
limiter = HierarchicalRateLimiter(config_path="config/rate-limits.yaml")

# Or use defaults (if file not found)
limiter = HierarchicalRateLimiter()
```

### Check Hierarchical Limits

```python
# Check all three levels (recommended)
allowed, reason = await limiter.check_all_limits(
    tenant_id="acme_corp",
    region="india"
)

if allowed:
    # Process the request
    process_call(...)
else:
    # Return 429 Too Many Requests
    return Response(reason, status_code=429)
```

### Individual Level Checks

```python
# Check tenant-level only
allowed, reason = await limiter.check_tenant_limit("acme_corp", "india")

# Check region-level only
allowed, reason = await limiter.check_region_limit("india")

# Check global-level only
allowed, reason = await limiter.check_global_limit()
```

### Backward Compatible IP/Stream Limits

```python
# Per-IP rate limit (100 requests/sec per IP)
allowed = await limiter.check_ip_limit("192.168.1.1")

# Per-stream rate limit (50 requests/sec per stream)
allowed = await limiter.check_stream_limit("stream_123")

# Cleanup when stream ends
await limiter.cleanup_stream("stream_123")
```

### Metrics & Monitoring

```python
# Get tenant-level metrics
metrics = await limiter.get_metrics(tenant_id="acme_corp")
print(f"Available tokens: {metrics['available_tokens']}")
print(f"Rate limit hits: {metrics['rate_limit_hits']}")
print(f"Queue depth: {metrics['queue_depth']}")

# Get global metrics
global_metrics = await limiter.get_metrics()
print(f"Global available tokens: {global_metrics['global_available_tokens']}")
print(f"Total rate limit hits: {global_metrics['total_rate_limit_hits']}")
```

## Integration with WebSocket Handler

The rate limiter integrates into the Exotel WebSocket handler to enforce limits before accepting calls:

```python
# In ExotelWebSocketHandler.handle()
async def handle(self, websocket):
    # Get tenant_id and region from request headers or JWT
    tenant_id = extract_tenant_id(websocket)
    region = get_region_from_ip(websocket.client.host)
    
    # Check hierarchical rate limits
    allowed, reason = await self.rate_limiter.check_all_limits(
        tenant_id=tenant_id,
        region=region
    )
    
    if not allowed:
        # Send 429 response
        await websocket.send_json({
            "event": "error",
            "error_code": 429,
            "message": reason
        })
        await websocket.close(code=429)
        return
    
    # Continue with normal call handling
    await handle_call(websocket, ...)
```

## Configuration Examples

### Example 1: Simple Setup (2 Regions)

```yaml
global:
  calls_per_minute: 500
  burst_capacity: 600

regions:
  india:
    calls_per_minute: 300
    burst_capacity: 360
  us:
    calls_per_minute: 200
    burst_capacity: 240

tiers:
  free:
    calls_per_minute: 10
    burst_capacity: 12
  pro:
    calls_per_minute: 100
    burst_capacity: 120
```

### Example 2: Enterprise Multi-Tenant

```yaml
global:
  calls_per_minute: 10000
  burst_capacity: 12000

regions:
  india:
    calls_per_minute: 5000
    burst_capacity: 6000
  us:
    calls_per_minute: 3000
    burst_capacity: 3600
  eu:
    calls_per_minute: 2000
    burst_capacity: 2400

tiers:
  enterprise:
    calls_per_minute: 1000
    burst_capacity: 1200

tenant_overrides:
  bank_of_india:
    calls_per_minute: 2000
    burst_capacity: 2400
    region: india
  global_corp:
    calls_per_minute: 5000
    burst_capacity: 6000
    region: us
```

### Example 3: Aggressive Limits (DDoS Protection)

```yaml
global:
  calls_per_minute: 1000
  burst_capacity: 1100  # Only 10% burst

regions:
  default:
    calls_per_minute: 100
    burst_capacity: 110

tiers:
  free:
    calls_per_minute: 5
    burst_capacity: 5  # No burst for free tier
```

## Updating Tenant Limits

### Add a New Tenant Override

Edit `config/rate-limits.yaml`:

```yaml
tenant_overrides:
  new_customer:
    tier: pro
    calls_per_minute: 200
    burst_capacity: 240
    region: india
```

Then reload:

```python
limiter.reload_config()
```

### Change Tier Limits Globally

Edit the tier definition in `config/rate-limits.yaml`:

```yaml
tiers:
  pro:
    calls_per_minute: 150  # Changed from 100
    burst_capacity: 180
```

Reload across all instances:

```python
# Each instance
limiter.reload_config()
```

## Monitoring & Alerting

### Prometheus Metrics

```python
from src.infrastructure.metrics import MetricsCollector

metrics = MetricsCollector()

# Record rate limit hit
metrics.record_rate_limit_hit(tenant_id="acme_corp", level="tenant")

# Set queue depth
metrics.set_queue_depth(tenant_id="acme_corp", depth=5)

# Set available tokens
metrics.set_available_tokens(tenant_id="acme_corp", level="tenant", tokens=50.0)

# Export to Prometheus
prometheus_text = metrics.export_metrics()
```

### Grafana Dashboard Example

Create a dashboard with:

- **Rate Limit Hits**: `increase(rate_limit_hits_total[5m])`
- **Queue Depth**: `rate_limit_queue_depth`
- **Available Tokens**: `rate_limit_available_tokens{level="tenant"}`
- **Rejection Rate**: `rate(rate_limit_hits_total[1m])`

### Alert Rules

```yaml
# Alert when approaching limit (80% consumed)
- alert: RateLimitApproaching
  expr: |
    rate_limit_available_tokens < 20
  for: 5m
  annotations:
    summary: "Tenant {{ $labels.tenant_id }} approaching rate limit"

# Alert when limit exceeded
- alert: RateLimitExceeded
  expr: |
    rate(rate_limit_hits_total[1m]) > 0
  for: 1m
  annotations:
    summary: "Rate limit hits detected for {{ $labels.tenant_id }}"
```

## Troubleshooting

### Problem: Requests Always Rejected (429)

**Diagnosis:**
```python
metrics = await limiter.get_metrics(tenant_id="acme_corp")
print(metrics['available_tokens'])  # Check token availability
```

**Solutions:**
- Check if burst capacity is reached: `available_tokens == 0`
- Wait for refill (depends on `calls_per_minute`)
- Increase `calls_per_minute` in config
- Check if global limit is exceeded

### Problem: Inconsistent Rate Limits

**Diagnosis:**
- Verify config file is being loaded: Check logs for "Loaded rate limit config"
- Check tier assignment: `print(limiter._get_tenant_limit("tenant_id"))`

**Solutions:**
- Ensure config file is valid YAML: `yaml.safe_load(open("config/rate-limits.yaml"))`
- Verify tenant exists in `tenant_overrides` if using custom limits
- Reload config after changes: `limiter.reload_config()`

### Problem: High Latency on Rate Limit Check

**Diagnosis:**
```python
import time
start = time.time()
allowed, _ = await limiter.check_all_limits(tenant, region)
elapsed = time.time() - start
print(f"Check took {elapsed*1000:.2f}ms")  # Should be <1ms
```

**Solutions:**
- Verify asyncio is being used (async/await)
- Check for lock contention: `limiter._lock` should rarely block
- Profile: Use `python3 -m cProfile`

## Best Practices

1. **Use Hierarchical Checks**: Always use `check_all_limits()` to enforce all three levels
2. **Set Realistic Burst**: Use 10-20% burst capacity (rate * 1.1 to rate * 1.2)
3. **Monitor Queue Depth**: Keep queue depth below 50% of max to prevent timeouts
4. **Update Config Dynamically**: Hot-reload instead of restarting for zero downtime
5. **Log Rate Limit Events**: Track rejections to debug customer issues
6. **Test Fallback**: Plan for behavior when rate limited (queue vs. reject)

## Performance Targets

✅ **Per-check latency**: <1ms  
✅ **Memory per bucket**: ~1KB  
✅ **Concurrent requests**: Unlimited (asyncio-safe)  
✅ **Config reload**: <100ms  
✅ **Throughput**: 1000+ checks/sec per core  

## References

- Token Bucket Algorithm: https://en.wikipedia.org/wiki/Token_bucket
- Rate Limiting Strategies: https://aws.amazon.com/blogs/architecture/rate-limiting-strategies-and-techniques/
- Prometheus Rate Limiting Metrics: https://prometheus.io/docs/concepts/metric_types/
