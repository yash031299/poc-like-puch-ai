"""
Stress and endurance testing.

Tests system behavior under extreme conditions and sustained load.
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.server import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestStressScenarios:
    """Stress test scenarios for extreme load."""

    def test_sustained_high_throughput_5sec(self, client):
        """Sustained high-throughput load for 5 seconds."""
        DURATION = 5  # seconds
        latencies = []
        errors = 0
        
        start_time = time.time()
        request_count = 0
        
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = []
            
            while time.time() - start_time < DURATION:
                future = executor.submit(
                    self._make_health_request,
                    client
                )
                futures.append(future)
                request_count += 1
            
            for future in as_completed(futures):
                try:
                    latency = future.result(timeout=10)
                    latencies.append(latency)
                except Exception:
                    errors += 1
        
        elapsed = time.time() - start_time
        throughput = len(latencies) / elapsed
        
        print(f"\n✓ 5-second sustained load:")
        print(f"  Requests: {len(latencies)}")
        print(f"  Throughput: {throughput:.0f} req/sec")
        print(f"  Errors: {errors}")
        print(f"  Avg latency: {mean(latencies) * 1000:.2f}ms")
        
        assert throughput > 100, f"Expected >100 req/sec, got {throughput:.0f}"
        assert errors == 0, f"Expected 0 errors, got {errors}"

    def test_burst_load_spikes(self, client):
        """Test recovery from sudden load spikes."""
        BASELINE_WORKERS = 10
        SPIKE_WORKERS = 100
        REQUESTS_PER_SPIKE = 500
        
        baseline_latencies = []
        spike_latencies = []
        post_spike_latencies = []
        
        with ThreadPoolExecutor(max_workers=SPIKE_WORKERS) as executor:
            # Baseline
            futures = [
                executor.submit(self._make_health_request, client)
                for _ in range(100)
            ]
            for future in as_completed(futures):
                baseline_latencies.append(future.result())
            
            # Spike
            futures = [
                executor.submit(self._make_health_request, client)
                for _ in range(REQUESTS_PER_SPIKE)
            ]
            for future in as_completed(futures):
                spike_latencies.append(future.result())
            
            # Post-spike
            futures = [
                executor.submit(self._make_health_request, client)
                for _ in range(100)
            ]
            for future in as_completed(futures):
                post_spike_latencies.append(future.result())
        
        baseline_avg = mean(baseline_latencies) * 1000
        spike_avg = mean(spike_latencies) * 1000
        post_spike_avg = mean(post_spike_latencies) * 1000
        
        print(f"\n✓ Load spike handling:")
        print(f"  Baseline: {baseline_avg:.2f}ms")
        print(f"  During spike (500 req): {spike_avg:.2f}ms")
        print(f"  Post-spike recovery: {post_spike_avg:.2f}ms")
        
        # Post-spike should be similar to baseline (recovery)
        recovery_ratio = post_spike_avg / baseline_avg
        print(f"  Recovery ratio: {recovery_ratio:.2f}x")
        
        assert recovery_ratio < 2.0, f"Expected quick recovery, got {recovery_ratio:.2f}x degradation"

    def test_resource_cleanup_under_sustained_load(self, client):
        """Verify resources are cleaned up during sustained load."""
        DURATION = 3
        NUM_WORKERS = 50
        
        start_time = time.time()
        request_count = 0
        errors = []
        
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = []
            
            while time.time() - start_time < DURATION:
                future = executor.submit(
                    self._make_passthru_request,
                    client,
                    request_count
                )
                futures.append(future)
                request_count += 1
                
                # Limit queue growth
                if len(futures) > NUM_WORKERS * 3:
                    for f in as_completed(futures, timeout=5):
                        try:
                            f.result()
                        except Exception as e:
                            errors.append(str(e))
                    futures = []
            
            # Collect remaining
            for future in as_completed(futures, timeout=10):
                try:
                    future.result()
                except Exception as e:
                    errors.append(str(e))
        
        print(f"\n✓ Resource cleanup test:")
        print(f"  Total requests: {request_count}")
        print(f"  Errors: {len(errors)}")
        
        error_rate = (len(errors) / max(request_count, 1)) * 100
        assert error_rate < 5, f"Expected <5% error rate, got {error_rate:.1f}%"

    def test_concurrent_user_simulation(self, client):
        """Simulate multiple concurrent users making requests."""
        NUM_USERS = 20
        REQUESTS_PER_USER = 50
        
        def user_session(user_id):
            user_latencies = []
            user_errors = 0
            
            for req_num in range(REQUESTS_PER_USER):
                try:
                    if req_num % 2 == 0:
                        start = time.time()
                        response = client.get("/health")
                        latency = time.time() - start
                        if response.status_code == 200:
                            user_latencies.append(latency)
                        else:
                            user_errors += 1
                    else:
                        start = time.time()
                        phone = f"+9199{user_id % 10000:05d}"
                        response = client.get(f"/passthru?action=dial&phones={phone}")
                        latency = time.time() - start
                        if response.status_code == 200:
                            user_latencies.append(latency)
                        else:
                            user_errors += 1
                except Exception:
                    user_errors += 1
            
            return user_latencies, user_errors
        
        all_latencies = []
        total_errors = 0
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=NUM_USERS) as executor:
            futures = [
                executor.submit(user_session, user_id)
                for user_id in range(NUM_USERS)
            ]
            
            for future in as_completed(futures):
                user_latencies, user_errors = future.result()
                all_latencies.extend(user_latencies)
                total_errors += user_errors
        
        elapsed = time.time() - start_time
        
        total_requests = NUM_USERS * REQUESTS_PER_USER
        throughput = total_requests / elapsed
        success_rate = ((total_requests - total_errors) / total_requests) * 100
        
        print(f"\n✓ Concurrent user simulation ({NUM_USERS} users):")
        print(f"  Total requests: {total_requests}")
        print(f"  Success rate: {success_rate:.1f}%")
        print(f"  Throughput: {throughput:.0f} req/sec")
        print(f"  Avg latency: {mean(all_latencies) * 1000:.2f}ms")
        print(f"  Max latency: {max(all_latencies) * 1000:.2f}ms")
        
        assert success_rate >= 95, f"Expected 95%+ success rate, got {success_rate:.1f}%"
        assert throughput > 50, f"Expected >50 req/sec, got {throughput:.0f}"

    @staticmethod
    def _make_health_request(client):
        """Helper: make health request and return latency."""
        start = time.time()
        response = client.get("/health")
        latency = time.time() - start
        assert response.status_code == 200
        return latency

    @staticmethod
    def _make_passthru_request(client, user_id):
        """Helper: make passthru request and return latency."""
        start = time.time()
        phone = f"+9199{user_id % 10000:05d}"
        response = client.get(f"/passthru?action=dial&phones={phone}")
        latency = time.time() - start
        assert response.status_code == 200
        return latency


class TestEnduranceLoad:
    """Long-running endurance tests."""

    def test_30sec_continuous_requests(self, client):
        """30-second continuous request stream."""
        DURATION = 30
        latencies = []
        errors = 0
        
        start_time = time.time()
        request_count = 0
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            
            while time.time() - start_time < DURATION:
                if request_count % 2 == 0:
                    future = executor.submit(
                        lambda: TestStressScenarios._make_health_request(client)
                    )
                else:
                    future = executor.submit(
                        lambda: TestStressScenarios._make_passthru_request(client, request_count)
                    )
                futures.append(future)
                request_count += 1
            
            for future in as_completed(futures, timeout=60):
                try:
                    latency = future.result()
                    latencies.append(latency)
                except Exception:
                    errors += 1
        
        elapsed = time.time() - start_time
        throughput = len(latencies) / elapsed
        
        print(f"\n✓ 30-second endurance test:")
        print(f"  Requests: {len(latencies)}")
        print(f"  Throughput: {throughput:.0f} req/sec")
        print(f"  Errors: {errors}")
        print(f"  Duration: {elapsed:.2f}s")
        
        assert throughput > 50, f"Expected >50 req/sec, got {throughput:.0f}"
        assert errors == 0, f"Expected 0 errors in endurance test, got {errors}"

    def test_latency_stability_over_time(self, client):
        """Verify latency remains stable over extended period."""
        DURATION = 20
        WINDOW_SIZE = 100  # requests per window
        
        windows = []
        current_window = []
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            
            while time.time() - start_time < DURATION:
                future = executor.submit(
                    TestStressScenarios._make_health_request,
                    client
                )
                futures.append(future)
                
                if len(futures) >= WINDOW_SIZE:
                    for f in as_completed(futures[:WINDOW_SIZE], timeout=10):
                        current_window.append(f.result())
                    
                    if len(current_window) >= WINDOW_SIZE:
                        windows.append(current_window)
                        current_window = []
                        futures = futures[WINDOW_SIZE:]
            
            # Final window
            for f in as_completed(futures, timeout=10):
                current_window.append(f.result())
            if current_window:
                windows.append(current_window)
        
        window_avgs = [mean(w) * 1000 for w in windows]
        
        print(f"\n✓ Latency stability test ({len(windows)} windows):")
        for i, avg in enumerate(window_avgs):
            print(f"  Window {i+1}: {avg:.2f}ms")
        
        # Latency should not degrade significantly over time
        if len(window_avgs) > 1:
            first_avg = window_avgs[0]
            last_avg = window_avgs[-1]
            degradation = ((last_avg - first_avg) / first_avg) * 100
            print(f"  Degradation: {degradation:+.1f}%")
            
            assert degradation < 50, f"Expected <50% degradation, got {degradation:+.1f}%"
