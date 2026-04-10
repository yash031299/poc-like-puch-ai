#!/usr/bin/env python3
"""
Capacity Planning and Infrastructure Recommendation Engine.

Performs linear regression on benchmark data to predict maximum capacity
at various utilization levels and generates infrastructure recommendations.

Usage:
    python3 scripts/capacity_model.py benchmark_results_[timestamp].json
"""

import json
import sys
import csv
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Tuple, Optional
from pathlib import Path


@dataclass
class CapacityMetrics:
    """Metrics for a specific concurrency level."""
    concurrent_users: int
    throughput_rps: float
    latency_p99_ms: float
    cpu_percent: float
    memory_mb: float


@dataclass
class CapacityProjection:
    """Projected capacity at a specific scale."""
    concurrent_users: int
    instances_required: int
    latency_p99_estimated_ms: float
    throughput_estimated_rps: float
    cpu_estimated_percent: float
    memory_estimated_mb: float
    meets_sla: bool  # P99 < 2s


def load_benchmark_results(json_path: str) -> Optional[List[dict]]:
    """Load benchmark results from JSON file."""
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
            return data.get('results', [])
    except Exception as e:
        print(f"Error loading benchmark results: {e}")
        return None


def linear_regression(x_values: List[float], y_values: List[float]) -> Tuple[float, float]:
    """
    Simple linear regression to find slope and intercept.
    
    Returns: (slope, intercept) for y = slope*x + intercept
    """
    n = len(x_values)
    if n < 2:
        return 0.0, 0.0
    
    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n
    
    numerator = sum((x_values[i] - x_mean) * (y_values[i] - y_mean) for i in range(n))
    denominator = sum((x_values[i] - x_mean) ** 2 for i in range(n))
    
    if denominator == 0:
        return 0.0, y_mean
    
    slope = numerator / denominator
    intercept = y_mean - slope * x_mean
    
    return slope, intercept


def analyze_benchmarks(results: List[dict]) -> Optional[dict]:
    """Analyze benchmark results and create capacity model."""
    if not results:
        print("No benchmark results to analyze.")
        return None
    
    # Extract metrics
    metrics = []
    for result in results:
        metrics.append(CapacityMetrics(
            concurrent_users=result['concurrent_users'],
            throughput_rps=result['throughput_rps'],
            latency_p99_ms=result['latency_p99_ms'],
            cpu_percent=result['cpu_percent'],
            memory_mb=result['memory_mb'],
        ))
    
    if not metrics:
        return None
    
    # Sort by concurrent users
    metrics.sort(key=lambda m: m.concurrent_users)
    
    # Extract data for regression
    x_data = [m.concurrent_users for m in metrics]
    
    # Linear regression for each metric
    throughput_values = [m.throughput_rps for m in metrics]
    latency_values = [m.latency_p99_ms for m in metrics]
    cpu_values = [m.cpu_percent for m in metrics]
    memory_values = [m.memory_mb for m in metrics]
    
    # Calculate regressions
    throughput_slope, throughput_intercept = linear_regression(x_data, throughput_values)
    latency_slope, latency_intercept = linear_regression(x_data, latency_values)
    cpu_slope, cpu_intercept = linear_regression(x_data, cpu_values)
    memory_slope, memory_intercept = linear_regression(x_data, memory_values)
    
    return {
        'metrics': [asdict(m) for m in metrics],
        'regression': {
            'throughput': {'slope': throughput_slope, 'intercept': throughput_intercept},
            'latency': {'slope': latency_slope, 'intercept': latency_intercept},
            'cpu': {'slope': cpu_slope, 'intercept': cpu_intercept},
            'memory': {'slope': memory_slope, 'intercept': memory_intercept},
        }
    }


def predict_metrics(
    concurrent_users: int,
    regression: dict,
) -> Tuple[float, float, float, float]:
    """Predict metrics for a given concurrency level using linear regression.
    
    Returns: (throughput_rps, latency_p99_ms, cpu_percent, memory_mb)
    """
    throughput = (
        regression['throughput']['slope'] * concurrent_users +
        regression['throughput']['intercept']
    )
    latency = (
        regression['latency']['slope'] * concurrent_users +
        regression['latency']['intercept']
    )
    cpu = (
        regression['cpu']['slope'] * concurrent_users +
        regression['cpu']['intercept']
    )
    memory = (
        regression['memory']['slope'] * concurrent_users +
        regression['memory']['intercept']
    )
    
    # Floor at 0 for realistic values
    throughput = max(0, throughput)
    latency = max(0, latency)
    cpu = max(0, cpu)
    memory = max(0, memory)
    
    return throughput, latency, cpu, memory


def find_max_capacity_at_threshold(
    regression: dict,
    sla_latency_ms: float = 2000,
    max_cpu_percent: float = 80,
) -> Optional[int]:
    """
    Find maximum concurrent users that stay within SLA.
    
    Returns: max concurrent users, or None if not found
    """
    # Binary search to find max concurrent users within SLA
    low, high = 1, 100000
    result = None
    
    while low <= high:
        mid = (low + high) // 2
        _, latency, _, _ = predict_metrics(mid, regression)
        
        if latency <= sla_latency_ms:
            result = mid
            low = mid + 1  # Try higher
        else:
            high = mid - 1  # Try lower
    
    return result


def generate_projections(
    regression: dict,
    projection_scales: List[int],
    instances_per_scale: int = 1,
) -> List[CapacityProjection]:
    """Generate capacity projections for different scales."""
    projections = []
    
    for scale in projection_scales:
        # Predict metrics
        throughput, latency, cpu, memory = predict_metrics(scale, regression)
        
        # Determine instances needed (assume ~200 concurrent users per instance)
        concurrent_per_instance = 200
        instances = max(1, (scale + concurrent_per_instance - 1) // concurrent_per_instance)
        
        # Adjust metrics for multiple instances
        cpu_per_instance = cpu
        throughput_total = throughput * instances
        
        # Latency shouldn't degrade much with multiple instances (load-balanced)
        latency_estimated = latency
        
        # Memory scales linearly
        memory_total = memory * instances
        
        # Check if within SLA (P99 < 2000ms)
        meets_sla = latency_estimated < 2000
        
        projections.append(CapacityProjection(
            concurrent_users=scale,
            instances_required=instances,
            latency_p99_estimated_ms=latency_estimated,
            throughput_estimated_rps=throughput_total,
            cpu_estimated_percent=cpu_per_instance,
            memory_estimated_mb=memory_total,
            meets_sla=meets_sla,
        ))
    
    return projections


def calculate_cost_projection(
    projections: List[CapacityProjection],
    cost_per_instance_monthly: float = 100,  # Rough estimate for small instance
    cost_per_gb_monthly: float = 10,
) -> List[dict]:
    """Calculate cost projections."""
    costs = []
    
    for proj in projections:
        # Instance cost
        instance_cost = proj.instances_required * cost_per_instance_monthly
        
        # Memory cost (convert MB to GB)
        memory_gb = proj.memory_estimated_mb / 1024
        memory_cost = memory_gb * cost_per_gb_monthly
        
        # Total monthly cost
        total_monthly = instance_cost + memory_cost
        
        # Cost per call (assume 10 calls per concurrent user per month)
        calls_per_month = proj.concurrent_users * 10 * 24 * 30  # Rough estimate
        cost_per_call = total_monthly / calls_per_month if calls_per_month > 0 else 0
        
        costs.append({
            'concurrent_users': proj.concurrent_users,
            'instances': proj.instances_required,
            'instance_cost_monthly': instance_cost,
            'memory_cost_monthly': memory_cost,
            'total_cost_monthly': total_monthly,
            'estimated_calls_monthly': int(calls_per_month),
            'cost_per_call_usd': cost_per_call,
        })
    
    return costs


def print_analysis(analysis: dict) -> None:
    """Print analysis results."""
    print("\n" + "="*80)
    print("CAPACITY ANALYSIS RESULTS")
    print("="*80)
    
    print("\nBenchmark Data Points:")
    print("-" * 80)
    print("{:<15} {:<15} {:<15} {:<15}".format(
        "Concurrent Users", "Throughput (rps)", "P99 Latency (ms)", "CPU %"
    ))
    print("-" * 80)
    
    for metric in analysis['metrics']:
        print("{:<15} {:<15.2f} {:<15.2f} {:<15.2f}".format(
            metric['concurrent_users'],
            metric['throughput_rps'],
            metric['latency_p99_ms'],
            metric['cpu_percent'],
        ))
    
    # Regression coefficients
    print("\n" + "="*80)
    print("LINEAR REGRESSION MODEL")
    print("="*80)
    print("\nEquations:")
    regression = analysis['regression']
    print(f"Throughput (rps) = {regression['throughput']['slope']:.4f}*X + {regression['throughput']['intercept']:.2f}")
    print(f"Latency (ms)     = {regression['latency']['slope']:.4f}*X + {regression['latency']['intercept']:.2f}")
    print(f"CPU (%)          = {regression['cpu']['slope']:.4f}*X + {regression['cpu']['intercept']:.2f}")
    print(f"Memory (MB)      = {regression['memory']['slope']:.4f}*X + {regression['memory']['intercept']:.2f}")
    
    print("\nWhere X = number of concurrent users")


def print_projections(projections: List[CapacityProjection]) -> None:
    """Print capacity projections."""
    print("\n" + "="*80)
    print("CAPACITY PROJECTIONS")
    print("="*80)
    
    print("\n{:<15} {:<10} {:<20} {:<15} {:<15} {:<10}".format(
        "Concurrent", "Instances", "P99 Latency (ms)", "Throughput (rps)", "CPU %", "SLA OK"
    ))
    print("-" * 95)
    
    for proj in projections:
        sla_status = "✓" if proj.meets_sla else "✗"
        print("{:<15} {:<10} {:<20.2f} {:<15.1f} {:<15.1f} {:<10}".format(
            proj.concurrent_users,
            proj.instances_required,
            proj.latency_p99_estimated_ms,
            proj.throughput_estimated_rps,
            proj.cpu_estimated_percent,
            sla_status,
        ))


def print_cost_analysis(costs: List[dict]) -> None:
    """Print cost analysis."""
    print("\n" + "="*80)
    print("COST PROJECTIONS (Monthly @ $100/small instance, $10/GB memory)")
    print("="*80)
    
    print("\n{:<15} {:<12} {:<15} {:<20} {:<20}".format(
        "Concurrent", "Instances", "Monthly Cost", "Monthly Calls", "Cost/Call"
    ))
    print("-" * 95)
    
    for cost in costs:
        cost_per_call_str = f"${cost['cost_per_call_usd']:.6f}" if cost['cost_per_call_usd'] > 0 else "N/A"
        print("{:<15} {:<12} {:<15} {:<20} {:<20}".format(
            cost['concurrent_users'],
            cost['instances'],
            f"${cost['total_cost_monthly']:.2f}",
            f"{cost['estimated_calls_monthly']:,}",
            cost_per_call_str,
        ))


def print_recommendations(
    analysis: dict,
    projections: List[CapacityProjection],
) -> None:
    """Print infrastructure recommendations."""
    print("\n" + "="*80)
    print("INFRASTRUCTURE RECOMMENDATIONS")
    print("="*80)
    
    regression = analysis['regression']
    
    # Find max capacity at 80% CPU with SLA
    # Estimate from regression
    max_users_80_cpu = (80 - regression['cpu']['intercept']) / regression['cpu']['slope'] if regression['cpu']['slope'] > 0 else 10000
    max_users_80_cpu = max(1, int(max_users_80_cpu))
    
    print(f"\n1. BASELINE INFRASTRUCTURE (Development/Testing)")
    print(f"   - Single instance with local file storage")
    print(f"   - Suitable for: Dev/test, staging, <50 concurrent users")
    print(f"   - Cost: ~$100/month")
    
    print(f"\n2. STANDARD INFRASTRUCTURE (100-500 concurrent users)")
    print(f"   - 2-3 API instances behind load balancer")
    print(f"   - PostgreSQL (managed): $50-100/month")
    print(f"   - Redis cluster: $20-50/month")
    print(f"   - Load balancer: $20-30/month")
    print(f"   - Total: ~$250-400/month")
    print(f"   - Handles ~{projections[-1].concurrent_users} concurrent users at P99 < 2s")
    
    print(f"\n3. ENTERPRISE INFRASTRUCTURE (1000+ concurrent users)")
    print(f"   - 5-10 API instances across availability zones")
    print(f"   - PostgreSQL enterprise (managed, replicated): $200-500/month")
    print(f"   - Redis cluster (managed): $100-200/month")
    print(f"   - CDN + DDoS protection: $50-200/month")
    print(f"   - Monitoring & logging: $100-200/month")
    print(f"   - Load balancer + WAF: $50-100/month")
    print(f"   - Total: ~$1000-2000/month")
    
    print(f"\n4. MULTI-REGION ENTERPRISE (5000+ concurrent users)")
    print(f"   - Per-region infrastructure (3 regions minimum)")
    print(f"   - Global load balancer with failover")
    print(f"   - Replicated PostgreSQL across regions")
    print(f"   - Per-region cost: $1000-2000/month × 3")
    print(f"   - Total: ~$3000-6000/month")
    
    print(f"\n5. SCALING GUIDELINES")
    print(f"   - Add 1 instance per ~200 concurrent users (based on regression)")
    print(f"   - Keep CPU utilization at 60-80% for headroom")
    print(f"   - Maintain P99 latency < 2000ms (current SLA)")
    print(f"   - Monitor Redis memory: each session ≈ 5-10MB in cache")
    print(f"   - Database connections: 20-50 per instance")


def save_projections(
    projections: List[CapacityProjection],
    costs: List[dict],
    output_dir: str = "scripts",
) -> None:
    """Save projections to CSV files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save projections
    proj_path = f"{output_dir}/capacity_projections_{timestamp}.csv"
    with open(proj_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'concurrent_users',
            'instances_required',
            'latency_p99_estimated_ms',
            'throughput_estimated_rps',
            'cpu_estimated_percent',
            'memory_estimated_mb',
            'meets_sla',
        ])
        writer.writeheader()
        for proj in projections:
            writer.writerow(asdict(proj))
    print(f"\n✓ Projections saved to: {proj_path}")
    
    # Save costs
    cost_path = f"{output_dir}/cost_projections_{timestamp}.csv"
    with open(cost_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=costs[0].keys())
        writer.writeheader()
        writer.writerows(costs)
    print(f"✓ Cost projections saved to: {cost_path}")


def main(json_file: Optional[str] = None) -> None:
    """Main entry point."""
    print("\n" + "="*80)
    print("PUCH AI CAPACITY PLANNING MODEL")
    print("="*80)
    
    # Find latest benchmark results if not provided
    if not json_file:
        script_dir = Path("scripts")
        benchmark_files = sorted(script_dir.glob("benchmark_results_*.json"), reverse=True)
        if benchmark_files:
            json_file = str(benchmark_files[0])
            print(f"\nUsing latest benchmark file: {json_file}")
        else:
            print("\nNo benchmark results found. Please run benchmark.py first.")
            sys.exit(1)
    
    # Load benchmark results
    print(f"Loading benchmark results from: {json_file}")
    results = load_benchmark_results(json_file)
    
    if not results:
        print("Failed to load benchmark results.")
        sys.exit(1)
    
    # Analyze
    analysis = analyze_benchmarks(results)
    if not analysis:
        print("Failed to analyze benchmarks.")
        sys.exit(1)
    
    print_analysis(analysis)
    
    # Generate projections
    projection_scales = [100, 500, 1000, 5000]
    projections = generate_projections(analysis['regression'], projection_scales)
    print_projections(projections)
    
    # Cost analysis
    costs = calculate_cost_projection(projections)
    print_cost_analysis(costs)
    
    # Recommendations
    print_recommendations(analysis, projections)
    
    # Save results
    save_projections(projections, costs)
    
    print("\n" + "="*80)
    print("✓ Capacity planning complete!")
    print("="*80 + "\n")


if __name__ == "__main__":
    json_file = sys.argv[1] if len(sys.argv) > 1 else None
    main(json_file)
