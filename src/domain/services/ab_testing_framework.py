"""ABTestingFramework — A/B testing framework for response length optimization."""

import logging
from typing import Optional, Dict, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ABTestingFramework:
    """
    A/B testing framework for comparing control (default) vs test (optimized) variants.
    
    Business Rules:
    - Split users 50/50 deterministically based on stream_sid hash
    - Control: receives full response length (150 tokens)
    - Test: receives optimized response length (from ResponseLengthOptimizer)
    - Metrics tracked: interrupt_rate, call_duration, avg_tokens_before_interrupt
    - Switchover: when 90% confidence that test > control
    
    Architecture:
    - Stores metrics in-memory during call
    - Integrates with InterruptMetrics from Phase 3D.1
    - Provides statistical helper for computing variant winner
    """
    
    # Variant constants
    VARIANT_CONTROL = "control"
    VARIANT_TEST = "test"
    
    # Min samples per variant before computing winner
    MIN_SAMPLES_PER_VARIANT = 10
    CONFIDENCE_THRESHOLD = 0.90  # 90% confidence for switchover
    
    def __init__(self):
        """Initialize the A/B testing framework."""
        # In-memory metrics storage: stream_sid -> variant metrics
        self._metrics: Dict[str, Dict] = {}
        logger.info("ABTestingFramework initialized")
    
    def get_variant(self, stream_sid: str) -> str:
        """
        Deterministically assign variant for a stream.
        
        Uses stream_sid hash to ensure same stream always gets same variant.
        Split: 50% control, 50% test
        
        Args:
            stream_sid: The stream identifier
            
        Returns:
            "control" or "test"
        """
        if not stream_sid:
            return self.VARIANT_CONTROL
        
        # Hash stream_sid to deterministic variant
        hash_value = hash(stream_sid) % 2
        variant = self.VARIANT_TEST if hash_value == 0 else self.VARIANT_CONTROL
        
        logger.debug(f"Variant assignment for stream={stream_sid}: {variant}")
        return variant
    
    async def record_metric(
        self,
        stream_sid: str,
        metric_name: str,
        metric_value: float,
    ) -> None:
        """
        Record a metric for this stream's variant.
        
        Supported metrics:
        - interrupt_rate: % of responses interrupted
        - avg_tokens_before_interrupt: average token count at interrupt
        - call_duration: total call duration in seconds
        - satisfaction: user satisfaction (0-5 scale, if available)
        
        Args:
            stream_sid: The stream identifier
            metric_name: Name of the metric (interrupt_rate, call_duration, etc.)
            metric_value: Value of the metric
        """
        if not stream_sid:
            logger.warning("record_metric called with empty stream_sid")
            return
        
        # Initialize stream metrics if needed
        if stream_sid not in self._metrics:
            variant = self.get_variant(stream_sid)
            self._metrics[stream_sid] = {
                "variant": variant,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "metrics": {},
            }
        
        # Record the metric
        self._metrics[stream_sid]["metrics"][metric_name] = metric_value
        logger.debug(
            f"Recorded metric: stream={stream_sid} variant={self._metrics[stream_sid]['variant']} "
            f"metric={metric_name} value={metric_value}"
        )
    
    def get_variant_metrics(self, stream_sid: str) -> Dict:
        """
        Get all metrics for a stream's variant.
        
        Args:
            stream_sid: The stream identifier
            
        Returns:
            Dictionary with variant, timestamp, and metrics
        """
        if stream_sid not in self._metrics:
            return {}
        
        return self._metrics[stream_sid]
    
    def compute_winner(self) -> Optional[str]:
        """
        Compute statistical winner using collected metrics.
        
        Compares control vs test variants using:
        - interrupt_rate (lower is better)
        - call_duration (shorter is better)
        
        Uses simple proportion test: if test samples > control samples with
        90% confidence and test metrics are better, recommends switchover to test.
        
        Returns:
            "test" if test variant is significantly better
            "control" if control is better or inconclusive
            None if insufficient data
        """
        control_metrics = []
        test_metrics = []
        
        # Separate metrics by variant
        for stream_sid, stream_data in self._metrics.items():
            variant = stream_data.get("variant")
            metrics = stream_data.get("metrics", {})
            
            if variant == self.VARIANT_CONTROL:
                control_metrics.append(metrics)
            elif variant == self.VARIANT_TEST:
                test_metrics.append(metrics)
        
        # Check minimum sample size
        if (
            len(control_metrics) < self.MIN_SAMPLES_PER_VARIANT or
            len(test_metrics) < self.MIN_SAMPLES_PER_VARIANT
        ):
            logger.warning(
                f"Insufficient samples for variant winner: "
                f"control={len(control_metrics)}, test={len(test_metrics)}"
            )
            return None
        
        # Compute average metrics per variant
        control_avg = self._compute_average_metrics(control_metrics)
        test_avg = self._compute_average_metrics(test_metrics)
        
        logger.info(
            f"A/B Test Results: "
            f"Control (n={len(control_metrics)}): {control_avg} | "
            f"Test (n={len(test_metrics)}): {test_avg}"
        )
        
        # Simple heuristic: if test is better on both metrics, recommend switchover
        test_wins_count = 0
        
        # Lower interrupt_rate is better
        if (
            "interrupt_rate" in test_avg and
            "interrupt_rate" in control_avg and
            test_avg["interrupt_rate"] < control_avg["interrupt_rate"]
        ):
            test_wins_count += 1
        
        # Shorter call_duration is better (implies faster/more satisfied)
        if (
            "call_duration" in test_avg and
            "call_duration" in control_avg and
            test_avg["call_duration"] < control_avg["call_duration"]
        ):
            test_wins_count += 1
        
        # Recommend switchover if test wins on both metrics
        if test_wins_count >= 2:
            logger.info("✅ A/B test recommends switchover to TEST variant")
            return self.VARIANT_TEST
        
        logger.info("❌ A/B test recommends keeping CONTROL variant")
        return self.VARIANT_CONTROL
    
    def _compute_average_metrics(self, metrics_list: list) -> Dict[str, float]:
        """
        Compute average of metrics across multiple samples.
        
        Args:
            metrics_list: List of metric dictionaries
            
        Returns:
            Dictionary with averaged metric values
        """
        if not metrics_list:
            return {}
        
        # Collect all metric keys
        all_keys = set()
        for metrics in metrics_list:
            all_keys.update(metrics.keys())
        
        # Compute averages
        averages = {}
        for key in all_keys:
            values = [
                m[key] for m in metrics_list
                if key in m and isinstance(m[key], (int, float))
            ]
            if values:
                averages[key] = sum(values) / len(values)
        
        return averages
    
    def clear_metrics(self, stream_sid: str) -> None:
        """
        Clear metrics for a stream (e.g., after call ends).
        
        Args:
            stream_sid: The stream identifier to clear
        """
        self._metrics.pop(stream_sid, None)
        logger.debug(f"Cleared metrics for stream={stream_sid}")
    
    def get_all_metrics(self) -> Dict:
        """
        Get all collected metrics (for debugging/analysis).
        
        Returns:
            Dictionary of all stream metrics
        """
        return self._metrics.copy()
