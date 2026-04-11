"""
HTTP endpoint load testing.

Tests concurrent requests to /health, /passthru under varying loads.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean, stdev

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.server import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestHealthEndpointLoad:
    """Load testing for /health endpoint."""

    def test_health_endpoint_throughput_sequential(self, client):
        """Measure sequential throughput (baseline)."""
        NUM_REQUESTS = 1000
        
        start_time = time.time()
        for _ in range(NUM_REQUESTS):
            response = client.get("/health")
            assert response.status_code == 200
        elapsed = time.time() - start_time
        
        throughput = NUM_REQUESTS / elapsed
        print(f"\n✓ Sequential throughput: {throughput:.0f} req/sec")
        
        assert throughput > 500, f"Expected >500 req/sec, got {throughput:.0f}"

    def test_health_endpoint_concurrent_100(self, client):
        """Load test with 100 concurrent requests."""
        NUM_REQUESTS = 100
        
        latencies = []
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            for _ in range(NUM_REQUESTS):
                future = executor.submit(self._request_health, client)
                futures.append(future)
            
            for future in as_completed(futures):
                latency = future.result()
                latencies.append(latency)
        
        elapsed = time.time() - start_time
        
        throughput = NUM_REQUESTS / elapsed
        avg_latency = mean(latencies) * 1000
        max_latency = max(latencies) * 1000
        min_latency = min(latencies) * 1000
        
        print(f"\n✓ 100 concurrent requests:")
        print(f"  Throughput: {throughput:.0f} req/sec")
        print(f"  Avg latency: {avg_latency:.2f}ms")
        print(f"  Min latency: {min_latency:.2f}ms")
        print(f"  Max latency: {max_latency:.2f}ms")
        
        assert throughput > 50, f"Expected >50 req/sec with concurrency, got {throughput:.0f}"
        assert avg_latency < 100, f"Expected avg <100ms, got {avg_latency:.2f}ms"
        assert max_latency < 500, f"Expected max <500ms, got {max_latency:.2f}ms"

    def test_health_endpoint_concurrent_500(self, client):
        """Stress test with 500 concurrent requests."""
        NUM_REQUESTS = 500
        
        latencies = []
        errors = 0
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = []
            for _ in range(NUM_REQUESTS):
                future = executor.submit(self._request_health, client)
                futures.append(future)
            
            for future in as_completed(futures):
                try:
                    latency = future.result()
                    latencies.append(latency)
                except Exception:
                    errors += 1
        
        elapsed = time.time() - start_time
        
        throughput = NUM_REQUESTS / elapsed
        success_rate = ((NUM_REQUESTS - errors) / NUM_REQUESTS) * 100
        avg_latency = mean(latencies) * 1000 if latencies else 0
        
        print(f"\n✓ 500 concurrent requests:")
        print(f"  Throughput: {throughput:.0f} req/sec")
        print(f"  Success rate: {success_rate:.1f}%")
        print(f"  Avg latency: {avg_latency:.2f}ms")
        print(f"  Errors: {errors}")
        
        assert success_rate >= 99, f"Expected 99%+ success rate, got {success_rate:.1f}%"
        assert throughput > 100, f"Expected >100 req/sec, got {throughput:.0f}"

    @staticmethod
    def _request_health(client):
        """Single health request with latency measurement."""
        start = time.time()
        response = client.get("/health")
        latency = time.time() - start
        assert response.status_code == 200
        return latency


class TestPassthruEndpointLoad:
    """Load testing for /passthru endpoint."""

    def test_passthru_endpoint_throughput_sequential(self, client):
        """Measure sequential passthru throughput."""
        NUM_REQUESTS = 500
        
        start_time = time.time()
        for _ in range(NUM_REQUESTS):
            response = client.get("/passthru?action=dial&phones=+919999999999")
            assert response.status_code == 200
        elapsed = time.time() - start_time
        
        throughput = NUM_REQUESTS / elapsed
        print(f"\n✓ Passthru sequential throughput: {throughput:.0f} req/sec")
        
        assert throughput > 100, f"Expected >100 req/sec, got {throughput:.0f}"

    def test_passthru_endpoint_concurrent_200(self, client):
        """Load test with 200 concurrent passthru requests."""
        NUM_REQUESTS = 200
        
        latencies = []
        
        with ThreadPoolExecutor(max_workers=25) as executor:
            futures = []
            for i in range(NUM_REQUESTS):
                phone = f"+9199{i % 10000:05d}"
                future = executor.submit(self._request_passthru, client, phone)
                futures.append(future)
            
            for future in as_completed(futures):
                latency = future.result()
                latencies.append(latency)
        
        throughput = NUM_REQUESTS / (max(latencies) + min(latencies))
        avg_latency = mean(latencies) * 1000
        max_latency = max(latencies) * 1000
        
        print(f"\n✓ 200 concurrent passthru requests:")
        print(f"  Avg latency: {avg_latency:.2f}ms")
        print(f"  Max latency: {max_latency:.2f}ms")
        
        assert avg_latency < 150, f"Expected avg <150ms, got {avg_latency:.2f}ms"
        assert max_latency < 600, f"Expected max <600ms, got {max_latency:.2f}ms"

    @staticmethod
    def _request_passthru(client, phone):
        """Single passthru request with latency measurement."""
        start = time.time()
        response = client.get(f"/passthru?action=dial&phones={phone}")
        latency = time.time() - start
        assert response.status_code == 200
        return latency


class TestEndpointUnderLoad:
    """Integration tests: endpoints under sustained load."""

    def test_mixed_endpoint_load(self, client):
        """Test both endpoints under load simultaneously."""
        NUM_HEALTH = 200
        NUM_PASSTHRU = 100
        
        latencies_health = []
        latencies_passthru = []
        errors = 0
        
        def health_request():
            try:
                start = time.time()
                response = client.get("/health")
                latency = time.time() - start
                if response.status_code == 200:
                    return ("health", latency)
                else:
                    return ("error", None)
            except Exception:
                return ("error", None)
        
        def passthru_request(i):
            try:
                start = time.time()
                phone = f"+9199{i % 10000:05d}"
                response = client.get(f"/passthru?action=dial&phones={phone}")
                latency = time.time() - start
                if response.status_code == 200:
                    return ("passthru", latency)
                else:
                    return ("error", None)
            except Exception:
                return ("error", None)
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = []
            for _ in range(NUM_HEALTH):
                futures.append(executor.submit(health_request))
            for i in range(NUM_PASSTHRU):
                futures.append(executor.submit(passthru_request, i))
            
            for future in as_completed(futures):
                endpoint_type, latency = future.result()
                if endpoint_type == "health":
                    latencies_health.append(latency)
                elif endpoint_type == "passthru":
                    latencies_passthru.append(latency)
                else:
                    errors += 1
        
        elapsed = time.time() - start_time
        
        success_rate = ((NUM_HEALTH + NUM_PASSTHRU - errors) / (NUM_HEALTH + NUM_PASSTHRU)) * 100
        
        print(f"\n✓ Mixed endpoint load (300 total requests):")
        print(f"  Health requests: {len(latencies_health)}")
        print(f"  Passthru requests: {len(latencies_passthru)}")
        print(f"  Success rate: {success_rate:.1f}%")
        print(f"  Total time: {elapsed:.2f}s")
        print(f"  Throughput: {(NUM_HEALTH + NUM_PASSTHRU) / elapsed:.0f} req/sec")
        
        if latencies_health:
            print(f"  Health avg: {mean(latencies_health) * 1000:.2f}ms")
        if latencies_passthru:
            print(f"  Passthru avg: {mean(latencies_passthru) * 1000:.2f}ms")
        
        assert success_rate >= 95, f"Expected 95%+ success rate, got {success_rate:.1f}%"
        assert errors < 20, f"Expected <20 errors, got {errors}"
