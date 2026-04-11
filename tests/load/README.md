# Load and Stress Testing Suite

Comprehensive load, stress, and endurance tests for the Exotel AgentStream voice AI PoC.

## Overview

This test suite validates system performance under various load conditions:

- **HTTP Load Tests** (`test_load_http.py`): Concurrent requests to `/health` and `/passthru` endpoints
- **WebSocket Load Tests** (`test_load_websocket.py`): Concurrent connections and audio streaming
- **Stress Tests** (`test_stress.py`): Extreme loads, load spikes, sustained stress, and endurance

## Running Tests

### All Load Tests
```bash
cd poc-like-puch-ai
pytest tests/load/ -v
```

### Specific Test Module
```bash
# HTTP endpoint load tests
pytest tests/load/test_load_http.py -v

# WebSocket load tests
pytest tests/load/test_load_websocket.py -v

# Stress and endurance tests
pytest tests/load/test_stress.py -v
```

### Single Test Class
```bash
# Test only health endpoint load
pytest tests/load/test_load_http.py::TestHealthEndpointLoad -v

# Test only WebSocket connections
pytest tests/load/test_load_websocket.py::TestWebSocketConnectionLoad -v

# Test only stress scenarios
pytest tests/load/test_stress.py::TestStressScenarios -v
```

### Single Test
```bash
# Test 500 concurrent requests
pytest tests/load/test_load_http.py::TestHealthEndpointLoad::test_health_endpoint_concurrent_500 -v

# Test sustained 5-second load
pytest tests/load/test_stress.py::TestStressScenarios::test_sustained_high_throughput_5sec -v
```

### Verbose Output with Performance Metrics
```bash
pytest tests/load/ -v -s
# -s flag shows print statements with throughput, latency, and error metrics
```

## Test Breakdown

### HTTP Load Tests (`test_load_http.py`)

#### TestHealthEndpointLoad
- **test_health_endpoint_throughput_sequential**: 1000 sequential requests (baseline throughput)
  - Expected: >500 req/sec
  - Measures: Sequential throughput baseline

- **test_health_endpoint_concurrent_100**: 100 concurrent requests
  - Expected: >50 req/sec, <100ms avg latency
  - Measures: Throughput, latency distribution, max latency

- **test_health_endpoint_concurrent_500**: 500 concurrent requests (stress)
  - Expected: 99%+ success rate, >100 req/sec
  - Measures: Success rate, throughput under high concurrency

#### TestPassthruEndpointLoad
- **test_passthru_endpoint_throughput_sequential**: 500 sequential passthru requests
  - Expected: >100 req/sec
  - Measures: Passthru endpoint throughput baseline

- **test_passthru_endpoint_concurrent_200**: 200 concurrent passthru requests
  - Expected: <150ms avg latency, <600ms max latency
  - Measures: Endpoint-specific latency under concurrency

#### TestEndpointUnderLoad
- **test_mixed_endpoint_load**: 300 mixed requests (200 health + 100 passthru) concurrently
  - Expected: 95%+ success rate, >50 total req/sec
  - Measures: Multi-endpoint behavior under simultaneous load

### WebSocket Load Tests (`test_load_websocket.py`)

#### TestWebSocketConnectionLoad
- **test_websocket_multiple_sequential_connections**: 50 sequential connection cycles
  - Expected: <1000ms avg connection latency
  - Measures: WebSocket connection overhead

- **test_websocket_concurrent_connection_setup**: 20 concurrent connections
  - Expected: 80%+ success rate
  - Measures: Concurrent connection handling, connection pool behavior

- **test_websocket_audio_streaming_under_load**: 10 concurrent connections streaming audio
  - Expected: 80%+ successful streams
  - Measures: Audio payload handling under concurrent load

#### TestWebSocketProtocolUnderLoad
- **test_message_ordering_concurrent_streams**: 5 concurrent streams with 20 messages each
  - Expected: Messages delivered in sequence number order
  - Measures: Protocol compliance under concurrent conditions

- **test_websocket_connection_resilience**: 100 rapid open/close cycles
  - Expected: 90%+ success rate
  - Measures: Connection lifecycle robustness

### Stress Tests (`test_stress.py`)

#### TestStressScenarios
- **test_sustained_high_throughput_5sec**: 5-second sustained high-concurrency load
  - Expected: >100 req/sec, 0 errors
  - Measures: System stability under sustained pressure

- **test_burst_load_spikes**: Load spike simulation (100→500 requests)
  - Expected: Quick recovery to baseline latency
  - Measures: Recovery from sudden load spikes

- **test_resource_cleanup_under_sustained_load**: 3-second sustained load with queue monitoring
  - Expected: <5% error rate
  - Measures: Resource cleanup and memory leaks

- **test_concurrent_user_simulation**: 20 users each making 50 requests
  - Expected: 95%+ success rate, >50 req/sec throughput
  - Measures: Multi-user concurrent session behavior

#### TestEnduranceLoad
- **test_30sec_continuous_requests**: 30-second continuous request stream
  - Expected: >50 req/sec, 0 errors
  - Measures: Extended stability and performance

- **test_latency_stability_over_time**: 20-second latency measurement by time windows
  - Expected: <50% latency degradation over time
  - Measures: Performance consistency and potential memory leaks

## Performance Baselines

### Expected Results (DEV_MODE)

| Metric | Target | Notes |
|--------|--------|-------|
| Health sequential | >500 req/sec | Baseline throughput |
| Health 100 concurrent | >50 req/sec | With stub providers |
| Health 500 concurrent | >100 req/sec | Stress test |
| Passthru sequential | >100 req/sec | API endpoint |
| Mixed load | >50 req/sec | Both endpoints |
| Avg latency | <100ms | Under normal load |
| Success rate | 95%+ | Error resilience |
| Connection setup | <1000ms | Per connection |
| Recovery time | 2-3s | After load spike |

### Expected Results (PROD with Gemini)

Results will be slower due to external API calls:

| Metric | Expected | Notes |
|--------|----------|-------|
| Health sequential | 200-400 req/sec | I/O bound |
| Health concurrent | 50-100 req/sec | Similar to DEV |
| Passthru sequential | 50-100 req/sec | With Gemini calls |
| Avg latency | 100-500ms | Gemini network + processing |
| Success rate | 90%+ | With API failures |

## Troubleshooting

### Test Failures

**WebSocket tests skip with "Connection refused"**
- Solution: Ensure server is running: `DEV_MODE=true python3 -m src.infrastructure.server`
- Verify port 8000 is available: `lsof -i :8000`

**High error rates in concurrent tests**
- Check system resources: `top`, `free -m`
- Reduce max_workers if system constrained
- Run tests one at a time instead of full suite

**Latency much higher than expected**
- System might be under other load
- Check for background processes: `top`
- Increase test duration to smooth out spikes

**WebSocket tests fail on "Too many open files"**
- Increase file descriptor limit: `ulimit -n 4096`
- Or reduce NUM_CONNECTIONS in tests

### Common Issues

#### Port Already in Use
```bash
# Find and kill process on port 8000
lsof -i :8000
kill -9 <PID>

# Or use different port
DEV_MODE=true python3 -m src.infrastructure.server --port 8001
```

#### Rate Limiting (429 errors)
- Tests trigger rate limiters if running too fast
- Add small delays between requests if needed
- Check server logs for rate limit configuration

#### Memory Pressure
- Monitor memory during long tests: `watch -n 1 'free -m'`
- If memory grows unbounded, indicates memory leak
- Check for proper resource cleanup in handlers

## Integration with CI/CD

### GitHub Actions Example
```yaml
- name: Run load tests
  run: |
    cd poc-like-puch-ai
    DEV_MODE=true pytest tests/load/test_load_http.py -v

- name: Run stress tests
  run: |
    cd poc-like-puch-ai
    DEV_MODE=true pytest tests/load/test_stress.py::TestStressScenarios -v
```

### Local CI Equivalent
```bash
#!/bin/bash
cd poc-like-puch-ai
export DEV_MODE=true

# Run fast tests first
pytest tests/load/test_load_http.py -v || exit 1

# Run stress tests (takes longer)
pytest tests/load/test_stress.py -v || exit 1

echo "✓ All load tests passed"
```

## Performance Optimization Tips

### Before Load Testing
1. Run `pytest tests/` to ensure all unit tests pass
2. Verify server starts cleanly: `DEV_MODE=true python3 -m src.infrastructure.server`
3. Check /health endpoint: `curl http://localhost:8000/health`

### During Load Testing
1. Monitor system resources: `top`, `iotop`, `vmstat`
2. Watch server logs for errors: tail logs in separate terminal
3. Use `-s` flag for verbose output: `pytest tests/load/ -v -s`

### After Load Testing
1. Review printed metrics (throughput, latency, errors)
2. Compare against baselines above
3. Investigate any tests that failed or had high error rates
4. Check for resource leaks (memory, file descriptors)

## Future Enhancements

### Recommended Additions
- [ ] **Distributed load testing**: Multiple machines generating load
- [ ] **Load profile simulation**: Realistic call patterns (morning peaks, evening valleys)
- [ ] **Audio quality metrics**: MOS score, latency impact on voice quality
- [ ] **Database stress tests**: Session repository under high concurrency
- [ ] **Failure injection**: Network delays, timeout scenarios
- [ ] **Long-running endurance**: 24-hour stability test
- [ ] **Memory profiling**: Track allocations during load
- [ ] **Latency percentiles**: p50, p95, p99 latency tracking

### Tools to Consider
- **locust** - Distributed load testing with Python
- **pytest-benchmark** - Performance benchmarking
- **memory-profiler** - Memory usage tracking
- **py-spy** - CPU profiling during tests

## References

- [Exotel AgentStream Protocol](https://docs.exotel.com/exotel-agentstream/agentstream)
- [FastAPI Performance](https://fastapi.tiangolo.com/deployment/performance/)
- [Load Testing Best Practices](https://en.wikipedia.org/wiki/Load_testing)
