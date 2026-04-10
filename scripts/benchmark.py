#!/usr/bin/env python3
"""
Comprehensive performance benchmarking and capacity planning.

Measures latency, throughput, and resource usage under various load levels.
Generates benchmark reports with recommendations.

Usage:
    python3 scripts/benchmark.py [--host localhost] [--port 8000]
"""

import asyncio
import csv
import json
import psutil
import time
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any
import aiohttp
from statistics import mean, median, quantiles

# Configuration
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000
HEALTH_CHECK_URL = "http://{host}:{port}/health"
CONCURRENT_LEVELS = [1, 10, 50, 100, 500]
REQUESTS_PER_LEVEL = 100  # Total requests per concurrency level
REQUEST_TIMEOUT = 30  # seconds


@dataclass
class BenchmarkResult:
    """Result from a single benchmark run."""
    concurrent_users: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    duration_seconds: float
    throughput_rps: float  # Requests per second
    latency_min_ms: float
    latency_max_ms: float
    latency_mean_ms: float
    latency_median_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    cpu_percent: float
    memory_mb: float
    memory_percent: float


@dataclass
class BenchmarkSuite:
    """Complete benchmark suite results."""
    timestamp: str
    host: str
    port: int
    results: List[BenchmarkResult] = field(default_factory=list)
    
    def add_result(self, result: BenchmarkResult) -> None:
        """Add a benchmark result."""
        self.results.append(result)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "host": self.host,
            "port": self.port,
            "results": [asdict(r) for r in self.results],
        }


async def check_health(session: aiohttp.ClientSession, url: str) -> bool:
    """Check if server is healthy."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        return False


async def benchmark_request(
    session: aiohttp.ClientSession,
    url: str,
    request_id: int,
) -> tuple[bool, float]:
    """
    Benchmark a single request.
    
    Returns: (success, latency_ms)
    """
    start_time = time.perf_counter()
    try:
        async with session.get(
            url, 
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        ) as resp:
            latency_ms = (time.perf_counter() - start_time) * 1000
            success = resp.status == 200
            return success, latency_ms
    except asyncio.TimeoutError:
        latency_ms = (time.perf_counter() - start_time) * 1000
        return False, latency_ms
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        return False, latency_ms


async def run_concurrent_requests(
    url: str,
    concurrent_count: int,
    total_requests: int,
) -> tuple[List[float], int, int]:
    """
    Run concurrent requests.
    
    Returns: (latencies, successful, failed)
    """
    latencies = []
    successful = 0
    failed = 0
    
    connector = aiohttp.TCPConnector(
        limit=concurrent_count * 2,  # Allow some buffer
        limit_per_host=concurrent_count * 2,
    )
    
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
    ) as session:
        tasks = []
        for i in range(total_requests):
            tasks.append(benchmark_request(session, url, i))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                failed += 1
            else:
                success, latency = result
                if success:
                    successful += 1
                    latencies.append(latency)
                else:
                    failed += 1
    
    return latencies, successful, failed


def get_system_stats() -> tuple[float, float, float]:
    """Get current system resource stats.
    
    Returns: (cpu_percent, memory_mb, memory_percent)
    """
    try:
        process = psutil.Process()
        cpu_percent = process.cpu_percent(interval=0.1)
        
        mem_info = process.memory_info()
        memory_mb = mem_info.rss / (1024 * 1024)
        
        memory_percent = process.memory_percent()
        
        return cpu_percent, memory_mb, memory_percent
    except Exception:
        return 0.0, 0.0, 0.0


async def run_benchmark(
    host: str,
    port: int,
    concurrent_count: int,
) -> BenchmarkResult | None:
    """Run benchmark for a specific concurrency level."""
    url = f"http://{host}:{port}/health"
    
    print(f"\n  Running benchmark for {concurrent_count} concurrent users...")
    print(f"  Total requests: {REQUESTS_PER_LEVEL}")
    
    # Get baseline stats
    cpu_before, mem_before, mem_pct_before = get_system_stats()
    
    # Run the benchmark
    start_time = time.perf_counter()
    latencies, successful, failed = await run_concurrent_requests(
        url,
        concurrent_count,
        REQUESTS_PER_LEVEL,
    )
    duration = time.perf_counter() - start_time
    
    # Get final stats
    cpu_after, mem_after, mem_pct_after = get_system_stats()
    
    if not latencies:
        print(f"  ✗ No successful requests!")
        return None
    
    # Calculate latency percentiles
    sorted_latencies = sorted(latencies)
    try:
        # Manual percentile calculation for compatibility
        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)
        latency_p95 = sorted_latencies[p95_idx]
        latency_p99 = sorted_latencies[p99_idx]
    except (IndexError, ValueError):
        latency_p95 = max(sorted_latencies)
        latency_p99 = max(sorted_latencies)
    
    result = BenchmarkResult(
        concurrent_users=concurrent_count,
        total_requests=REQUESTS_PER_LEVEL,
        successful_requests=successful,
        failed_requests=failed,
        duration_seconds=duration,
        throughput_rps=REQUESTS_PER_LEVEL / duration,
        latency_min_ms=min(latencies),
        latency_max_ms=max(latencies),
        latency_mean_ms=mean(latencies),
        latency_median_ms=median(latencies),
        latency_p95_ms=latency_p95,
        latency_p99_ms=latency_p99,
        cpu_percent=max(cpu_before, cpu_after),
        memory_mb=max(mem_before, mem_after),
        memory_percent=max(mem_pct_before, mem_pct_after),
    )
    
    # Print results
    print(f"  ✓ Completed in {duration:.2f}s")
    print(f"    Throughput: {result.throughput_rps:.1f} req/s")
    print(f"    Latency: p50={result.latency_median_ms:.1f}ms, p95={result.latency_p95_ms:.1f}ms, p99={result.latency_p99_ms:.1f}ms")
    print(f"    Resource: CPU={result.cpu_percent:.1f}%, MEM={result.memory_mb:.1f}MB ({result.memory_percent:.1f}%)")
    
    return result


async def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> BenchmarkSuite:
    """Run the complete benchmark suite."""
    print("\n" + "="*70)
    print("PUCH AI PERFORMANCE BENCHMARKING SUITE")
    print("="*70)
    
    # Check server health
    print(f"\nChecking server health at {host}:{port}...")
    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector) as session:
        health_url = f"http://{host}:{port}/health"
        is_healthy = await check_health(session, health_url)
    
    if not is_healthy:
        print(f"✗ Server at {host}:{port} is not responding. Please start the server.")
        sys.exit(1)
    
    print("✓ Server is healthy\n")
    
    suite = BenchmarkSuite(
        timestamp=datetime.now().isoformat(),
        host=host,
        port=port,
    )
    
    print("Starting benchmarks...\n")
    
    for concurrent_level in CONCURRENT_LEVELS:
        try:
            result = await run_benchmark(host, port, concurrent_level)
            if result:
                suite.add_result(result)
            # Small delay between levels
            await asyncio.sleep(1)
        except Exception as e:
            print(f"✗ Error during benchmark for {concurrent_level} concurrent users: {e}")
            continue
    
    return suite


def print_summary(suite: BenchmarkSuite) -> None:
    """Print a human-readable summary of results."""
    print("\n" + "="*70)
    print("BENCHMARK RESULTS SUMMARY")
    print("="*70)
    
    if not suite.results:
        print("No benchmark results available.")
        return
    
    # Table header
    print("\n{:<8} {:<10} {:<12} {:<12} {:<12} {:<10} {:<10} {:<12}".format(
        "Users", "Throughput", "P50 (ms)", "P95 (ms)", "P99 (ms)", 
        "CPU %", "MEM (MB)", "Success %"
    ))
    print("-" * 100)
    
    # Table rows
    for result in suite.results:
        success_pct = (result.successful_requests / result.total_requests * 100) if result.total_requests > 0 else 0
        print("{:<8} {:<10.1f} {:<12.2f} {:<12.2f} {:<12.2f} {:<10.1f} {:<10.1f} {:<12.1f}".format(
            result.concurrent_users,
            result.throughput_rps,
            result.latency_median_ms,
            result.latency_p95_ms,
            result.latency_p99_ms,
            result.cpu_percent,
            result.memory_mb,
            success_pct,
        ))
    
    print("\n" + "="*70)
    print("KEY FINDINGS")
    print("="*70)
    
    max_result = max(suite.results, key=lambda r: r.concurrent_users)
    print(f"\nMax Concurrent Users Tested: {max_result.concurrent_users}")
    print(f"  - Throughput: {max_result.throughput_rps:.1f} req/s")
    print(f"  - P99 Latency: {max_result.latency_p99_ms:.2f}ms")
    print(f"  - CPU Usage: {max_result.cpu_percent:.1f}%")
    print(f"  - Memory Usage: {max_result.memory_mb:.1f}MB")
    
    # Find max at 2s p99 latency constraint
    viable_results = [r for r in suite.results if r.latency_p99_ms < 2000]  # 2s threshold
    if viable_results:
        max_viable = max(viable_results, key=lambda r: r.concurrent_users)
        print(f"\nMax Concurrent Users (P99 < 2000ms): {max_viable.concurrent_users}")
        print(f"  - P99 Latency: {max_viable.latency_p99_ms:.2f}ms")
        print(f"  - Throughput: {max_viable.throughput_rps:.1f} req/s")
    
    print("\n" + "="*70)


def save_results(suite: BenchmarkSuite, base_path: str = "scripts") -> None:
    """Save results to JSON and CSV files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # JSON output
    json_path = f"{base_path}/benchmark_results_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(suite.to_dict(), f, indent=2)
    print(f"\n✓ JSON results saved to: {json_path}")
    
    # CSV output
    csv_path = f"{base_path}/benchmark_results_{timestamp}.csv"
    if suite.results:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=asdict(suite.results[0]).keys())
            writer.writeheader()
            for result in suite.results:
                writer.writerow(asdict(result))
    print(f"✓ CSV results saved to: {csv_path}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Performance benchmark for Puch AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Server host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Server port (default: {DEFAULT_PORT})",
    )
    
    args = parser.parse_args()
    
    # Run benchmark
    suite = asyncio.run(main(args.host, args.port))
    
    # Print summary
    print_summary(suite)
    
    # Save results
    try:
        save_results(suite)
    except Exception as e:
        print(f"Warning: Could not save results: {e}")
    
    print("\n✓ Benchmarking complete!")
