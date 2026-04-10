"""Unit tests for ABTestingFramework service (Phase 3D.5)."""

import pytest
import asyncio
from src.domain.services.ab_testing_framework import ABTestingFramework


class TestABTestingFramework:
    """Test suite for A/B testing framework."""
    
    @pytest.fixture
    def framework(self):
        """Create a fresh ABTestingFramework instance for each test."""
        return ABTestingFramework()
    
    def test_get_variant_deterministic_assignment(self, framework):
        """Test: Variant assignment is deterministic (same stream → same variant)."""
        variant1 = framework.get_variant("stream_123")
        variant2 = framework.get_variant("stream_123")
        
        assert variant1 == variant2
        assert variant1 in (ABTestingFramework.VARIANT_CONTROL, ABTestingFramework.VARIANT_TEST)
    
    def test_get_variant_different_streams_split(self, framework):
        """Test: Different streams get different variants (50/50 split)."""
        # Generate 20 different stream IDs and check if we get roughly 50/50 split
        variants = {}
        for i in range(20):
            stream_id = f"stream_{i}"
            variant = framework.get_variant(stream_id)
            variants[variant] = variants.get(variant, 0) + 1
        
        # Both variants should be present (allowing some variance)
        assert ABTestingFramework.VARIANT_CONTROL in variants
        assert ABTestingFramework.VARIANT_TEST in variants
        
        # Should be roughly balanced (not requiring exact 50/50)
        assert abs(variants[ABTestingFramework.VARIANT_CONTROL] - 10) <= 5
        assert abs(variants[ABTestingFramework.VARIANT_TEST] - 10) <= 5
    
    def test_get_variant_empty_stream_id(self, framework):
        """Test: Empty stream_id returns control variant."""
        variant = framework.get_variant("")
        assert variant == ABTestingFramework.VARIANT_CONTROL
    
    def test_get_variant_none_stream_id(self, framework):
        """Test: None stream_id returns control variant."""
        variant = framework.get_variant(None)
        assert variant == ABTestingFramework.VARIANT_CONTROL
    
    @pytest.mark.asyncio
    async def test_record_metric_basic(self, framework):
        """Test: record_metric stores metrics correctly."""
        stream_id = "test_stream"
        await framework.record_metric(stream_id, "interrupt_rate", 0.25)
        
        metrics = framework.get_variant_metrics(stream_id)
        assert metrics["variant"] in (ABTestingFramework.VARIANT_CONTROL, ABTestingFramework.VARIANT_TEST)
        assert metrics["metrics"]["interrupt_rate"] == 0.25
    
    @pytest.mark.asyncio
    async def test_record_metric_multiple_metrics(self, framework):
        """Test: Multiple metrics can be recorded for same stream."""
        stream_id = "test_stream"
        await framework.record_metric(stream_id, "interrupt_rate", 0.3)
        await framework.record_metric(stream_id, "call_duration", 45.5)
        await framework.record_metric(stream_id, "satisfaction", 4.0)
        
        metrics = framework.get_variant_metrics(stream_id)
        assert metrics["metrics"]["interrupt_rate"] == 0.3
        assert metrics["metrics"]["call_duration"] == 45.5
        assert metrics["metrics"]["satisfaction"] == 4.0
    
    @pytest.mark.asyncio
    async def test_record_metric_empty_stream_id(self, framework):
        """Test: record_metric handles empty stream_id gracefully."""
        # Should not crash, just log warning
        await framework.record_metric("", "interrupt_rate", 0.25)
        
        metrics = framework.get_variant_metrics("")
        assert metrics == {}
    
    def test_compute_winner_insufficient_samples(self, framework):
        """Test: compute_winner returns None with insufficient samples."""
        # Add only 5 samples per variant (min is 10)
        for i in range(5):
            framework._metrics[f"control_stream_{i}"] = {
                "variant": ABTestingFramework.VARIANT_CONTROL,
                "metrics": {"interrupt_rate": 0.25, "call_duration": 40.0},
            }
        
        for i in range(5):
            framework._metrics[f"test_stream_{i}"] = {
                "variant": ABTestingFramework.VARIANT_TEST,
                "metrics": {"interrupt_rate": 0.20, "call_duration": 35.0},
            }
        
        winner = framework.compute_winner()
        assert winner is None
    
    def test_compute_winner_test_variant_better(self, framework):
        """Test: compute_winner recommends TEST when test has better metrics."""
        # Add sufficient control samples (worse metrics)
        for i in range(10):
            framework._metrics[f"control_stream_{i}"] = {
                "variant": ABTestingFramework.VARIANT_CONTROL,
                "metrics": {
                    "interrupt_rate": 0.40,      # Higher is worse
                    "call_duration": 60.0,        # Longer is worse
                },
            }
        
        # Add sufficient test samples (better metrics)
        for i in range(10):
            framework._metrics[f"test_stream_{i}"] = {
                "variant": ABTestingFramework.VARIANT_TEST,
                "metrics": {
                    "interrupt_rate": 0.20,      # Lower is better
                    "call_duration": 40.0,        # Shorter is better
                },
            }
        
        winner = framework.compute_winner()
        assert winner == ABTestingFramework.VARIANT_TEST
    
    def test_compute_winner_control_variant_better(self, framework):
        """Test: compute_winner recommends CONTROL when control has better metrics."""
        # Add sufficient control samples (better metrics)
        for i in range(10):
            framework._metrics[f"control_stream_{i}"] = {
                "variant": ABTestingFramework.VARIANT_CONTROL,
                "metrics": {
                    "interrupt_rate": 0.15,      # Lower is better
                    "call_duration": 30.0,        # Shorter is better
                },
            }
        
        # Add sufficient test samples (worse metrics)
        for i in range(10):
            framework._metrics[f"test_stream_{i}"] = {
                "variant": ABTestingFramework.VARIANT_TEST,
                "metrics": {
                    "interrupt_rate": 0.35,      # Higher is worse
                    "call_duration": 50.0,        # Longer is worse
                },
            }
        
        winner = framework.compute_winner()
        assert winner == ABTestingFramework.VARIANT_CONTROL
    
    def test_clear_metrics(self, framework):
        """Test: clear_metrics removes stream metrics."""
        stream_id = "test_stream"
        framework._metrics[stream_id] = {
            "variant": ABTestingFramework.VARIANT_CONTROL,
            "metrics": {"interrupt_rate": 0.25},
        }
        
        assert framework.get_variant_metrics(stream_id) != {}
        framework.clear_metrics(stream_id)
        assert framework.get_variant_metrics(stream_id) == {}
    
    def test_get_all_metrics(self, framework):
        """Test: get_all_metrics returns copy of all metrics."""
        framework._metrics["stream_1"] = {
            "variant": ABTestingFramework.VARIANT_CONTROL,
            "metrics": {"interrupt_rate": 0.25},
        }
        framework._metrics["stream_2"] = {
            "variant": ABTestingFramework.VARIANT_TEST,
            "metrics": {"interrupt_rate": 0.20},
        }
        
        all_metrics = framework.get_all_metrics()
        assert len(all_metrics) == 2
        assert "stream_1" in all_metrics
        assert "stream_2" in all_metrics
        
        # Verify it's a copy (modifications don't affect original)
        all_metrics["stream_3"] = {}
        assert "stream_3" not in framework._metrics
