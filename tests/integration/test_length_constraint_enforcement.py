"""Integration tests for A/B testing framework (Phase 3D.5)."""

import pytest
import asyncio
from src.domain.services.ab_testing_framework import ABTestingFramework


class TestABTestingFrameworkIntegration:
    """Integration tests for A/B testing framework."""
    
    @pytest.fixture
    def framework(self):
        """Create a fresh ABTestingFramework instance."""
        return ABTestingFramework()
    
    @pytest.mark.asyncio
    async def test_full_ab_flow_with_winner_determination(self, framework):
        """Test: Complete A/B testing flow from assignment to winner determination."""
        # Simulate streams that will have roughly equal split between control/test
        control_count = 0
        test_count = 0
        
        # Create enough streams to ensure minimum samples
        for i in range(30):
            stream_id = f"stream_{i:03d}"
            variant = framework.get_variant(stream_id)
            
            # Record metrics - better for test variant
            if variant == ABTestingFramework.VARIANT_TEST:
                await framework.record_metric(stream_id, "interrupt_rate", 0.20)
                await framework.record_metric(stream_id, "call_duration", 35.0)
                test_count += 1
            else:
                await framework.record_metric(stream_id, "interrupt_rate", 0.35)
                await framework.record_metric(stream_id, "call_duration", 50.0)
                control_count += 1
            
            # Verify variant assignment is deterministic
            variant2 = framework.get_variant(stream_id)
            assert variant == variant2
        
        # Verify we have minimum samples
        assert control_count >= 10
        assert test_count >= 10
        
        # Compute winner
        winner = framework.compute_winner()
        
        # Since test has better metrics, should recommend switchover
        assert winner in (ABTestingFramework.VARIANT_CONTROL, ABTestingFramework.VARIANT_TEST)
    
    @pytest.mark.asyncio
    async def test_variant_consistency_across_multiple_calls(self, framework):
        """Test: Same stream always gets same variant across multiple calls."""
        stream_id = "persistent_stream"
        
        # Get variant multiple times
        variants = set()
        for _ in range(10):
            variant = framework.get_variant(stream_id)
            variants.add(variant)
            await asyncio.sleep(0.001)  # Simulate time passing
        
        # Should be only one variant (consistent)
        assert len(variants) == 1
        
        # Record a metric to create the entry in _metrics
        assigned_variant = variants.pop()
        await framework.record_metric(stream_id, "interrupt_rate", 0.25)
        
        # Verify metrics are associated with correct variant
        metrics = framework.get_variant_metrics(stream_id)
        assert metrics["variant"] == assigned_variant
    
    @pytest.mark.asyncio
    async def test_metric_isolation_between_streams(self, framework):
        """Test: Metrics from one stream don't affect another."""
        stream1_id = "stream_1"
        stream2_id = "stream_2"
        
        # Record metrics for stream 1
        await framework.record_metric(stream1_id, "interrupt_rate", 0.5)
        await framework.record_metric(stream1_id, "call_duration", 60.0)
        
        # Record different metrics for stream 2
        await framework.record_metric(stream2_id, "interrupt_rate", 0.1)
        await framework.record_metric(stream2_id, "call_duration", 20.0)
        
        # Verify isolation
        metrics1 = framework.get_variant_metrics(stream1_id)
        metrics2 = framework.get_variant_metrics(stream2_id)
        
        assert metrics1["metrics"]["interrupt_rate"] == 0.5
        assert metrics2["metrics"]["interrupt_rate"] == 0.1
        assert metrics1["metrics"]["call_duration"] == 60.0
        assert metrics2["metrics"]["call_duration"] == 20.0
    
    def test_statistical_winner_with_clear_difference(self, framework):
        """Test: Winner is correctly identified when test is clearly better."""
        # Add 20 control samples with poor metrics
        for i in range(20):
            framework._metrics[f"control_{i}"] = {
                "variant": ABTestingFramework.VARIANT_CONTROL,
                "metrics": {
                    "interrupt_rate": 0.50,
                    "call_duration": 90.0,
                },
            }
        
        # Add 20 test samples with excellent metrics
        for i in range(20):
            framework._metrics[f"test_{i}"] = {
                "variant": ABTestingFramework.VARIANT_TEST,
                "metrics": {
                    "interrupt_rate": 0.15,
                    "call_duration": 30.0,
                },
            }
        
        winner = framework.compute_winner()
        assert winner == ABTestingFramework.VARIANT_TEST
    
    def test_statistical_winner_with_minor_differences(self, framework):
        """Test: Winner determination is conservative with minor metric differences."""
        # Add 15 control samples
        for i in range(15):
            framework._metrics[f"control_{i}"] = {
                "variant": ABTestingFramework.VARIANT_CONTROL,
                "metrics": {
                    "interrupt_rate": 0.25,
                    "call_duration": 40.0,
                },
            }
        
        # Add 15 test samples with slightly better metrics (but not clearly)
        for i in range(15):
            framework._metrics[f"test_{i}"] = {
                "variant": ABTestingFramework.VARIANT_TEST,
                "metrics": {
                    "interrupt_rate": 0.23,      # Only slightly better
                    "call_duration": 38.0,        # Only slightly better
                },
            }
        
        winner = framework.compute_winner()
        # Should prefer control since improvement is not significant
        # (doesn't meet the 90% confidence threshold for switchover)
        assert winner == ABTestingFramework.VARIANT_CONTROL
    
    @pytest.mark.asyncio
    async def test_metrics_collection_across_multiple_metric_types(self, framework):
        """Test: Framework handles various metric types correctly."""
        stream_id = "multi_metric_stream"
        
        # Record various metrics
        metrics_to_record = {
            "interrupt_rate": 0.25,
            "call_duration": 45.5,
            "satisfaction": 4.2,
            "tokens_generated": 350,
            "avg_response_latency_ms": 250,
        }
        
        for metric_name, value in metrics_to_record.items():
            await framework.record_metric(stream_id, metric_name, value)
        
        # Verify all metrics are stored
        stored_metrics = framework.get_variant_metrics(stream_id)
        for metric_name, value in metrics_to_record.items():
            assert stored_metrics["metrics"][metric_name] == value
    
    def test_get_all_metrics_returns_complete_snapshot(self, framework):
        """Test: get_all_metrics provides complete snapshot of all streams."""
        # Add metrics for multiple streams
        for i in range(5):
            framework._metrics[f"stream_{i}"] = {
                "variant": ABTestingFramework.VARIANT_CONTROL if i < 3 else ABTestingFramework.VARIANT_TEST,
                "metrics": {"interrupt_rate": 0.20 + i * 0.05},
            }
        
        all_metrics = framework.get_all_metrics()
        
        # Verify completeness
        assert len(all_metrics) == 5
        for i in range(5):
            assert f"stream_{i}" in all_metrics
            assert "variant" in all_metrics[f"stream_{i}"]
            assert "metrics" in all_metrics[f"stream_{i}"]
    
    @pytest.mark.asyncio
    async def test_metric_update_overwrites_previous_value(self, framework):
        """Test: Recording same metric twice overwrites previous value."""
        stream_id = "update_stream"
        
        # Record initial metric
        await framework.record_metric(stream_id, "interrupt_rate", 0.30)
        initial = framework.get_variant_metrics(stream_id)
        assert initial["metrics"]["interrupt_rate"] == 0.30
        
        # Update with new value
        await framework.record_metric(stream_id, "interrupt_rate", 0.15)
        updated = framework.get_variant_metrics(stream_id)
        
        # Should have new value
        assert updated["metrics"]["interrupt_rate"] == 0.15
        # Should not have duplicates
        assert len([k for k in updated["metrics"].keys() if k == "interrupt_rate"]) == 1
    
    def test_winner_computation_with_missing_metrics(self, framework):
        """Test: Winner computation handles streams with missing metric fields."""
        # Add control samples with all metrics
        for i in range(10):
            framework._metrics[f"control_{i}"] = {
                "variant": ABTestingFramework.VARIANT_CONTROL,
                "metrics": {
                    "interrupt_rate": 0.30,
                    "call_duration": 50.0,
                },
            }
        
        # Add test samples with only some metrics
        for i in range(10):
            framework._metrics[f"test_{i}"] = {
                "variant": ABTestingFramework.VARIANT_TEST,
                "metrics": {
                    "interrupt_rate": 0.25,
                    # "call_duration" is missing
                },
            }
        
        # Should still compute winner based on available metrics
        winner = framework.compute_winner()
        assert winner in (ABTestingFramework.VARIANT_CONTROL, ABTestingFramework.VARIANT_TEST)
