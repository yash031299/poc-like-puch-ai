"""Tests for FallbackStrategy and fallback error recovery."""

import pytest
from src.domain.services.fallback_handler import (
    FallbackExhaustedError,
    FallbackLevel,
    FallbackStrategy,
)


class TestFallbackLevel:
    """Test FallbackLevel enum."""

    def test_fallback_level_hierarchy(self):
        """Verify fallback level hierarchy."""
        assert FallbackLevel.PRIMARY.value == 0
        assert FallbackLevel.SECONDARY.value == 1
        assert FallbackLevel.TERTIARY.value == 2

    def test_fallback_level_names(self):
        """Verify fallback level names."""
        assert FallbackLevel.PRIMARY.name == "PRIMARY"
        assert FallbackLevel.SECONDARY.name == "SECONDARY"
        assert FallbackLevel.TERTIARY.name == "TERTIARY"


class TestFallbackStrategyInitialization:
    """Test FallbackStrategy initialization and state management."""

    def test_initialize_at_primary(self):
        """Verify strategy starts at PRIMARY level."""
        strategy = FallbackStrategy()
        assert strategy.get_level() == FallbackLevel.PRIMARY

    def test_initialize_zero_hops(self):
        """Verify strategy starts with zero hops."""
        strategy = FallbackStrategy()
        assert strategy._hop_count == 0

    def test_set_level(self):
        """Verify level can be set."""
        strategy = FallbackStrategy()
        strategy.set_level(FallbackLevel.SECONDARY)
        assert strategy.get_level() == FallbackLevel.SECONDARY

    def test_reset(self):
        """Verify reset returns to primary with zero hops."""
        strategy = FallbackStrategy()
        strategy.set_level(FallbackLevel.TERTIARY)
        strategy._hop_count = 2
        strategy.reset()
        assert strategy.get_level() == FallbackLevel.PRIMARY
        assert strategy._hop_count == 0


class TestFallbackStrategyDepth:
    """Test cascade prevention and depth tracking."""

    def test_increment_depth_once(self):
        """Verify depth increments to 1."""
        strategy = FallbackStrategy()
        strategy.increment_depth()
        assert strategy._hop_count == 1

    def test_increment_depth_twice(self):
        """Verify depth increments to 2."""
        strategy = FallbackStrategy()
        strategy.increment_depth()
        strategy.increment_depth()
        assert strategy._hop_count == 2

    def test_increment_depth_exceeds_max(self):
        """Verify FallbackExhaustedError on max hop exceeding."""
        strategy = FallbackStrategy()
        strategy._hop_count = 2
        with pytest.raises(FallbackExhaustedError):
            strategy.increment_depth()

    def test_max_hops_limit(self):
        """Verify max hops is 2."""
        strategy = FallbackStrategy()
        assert strategy._max_hops == 2


class TestFallbackStrategyExecution:
    """Test three-tier fallback execution."""

    @pytest.mark.asyncio
    async def test_primary_success(self):
        """Verify primary success returns immediately."""
        strategy = FallbackStrategy()

        async def primary():
            return "primary_result"

        async def secondary():
            raise ValueError("Secondary should not be called")

        async def tertiary():
            raise ValueError("Tertiary should not be called")

        result = await strategy.execute_with_fallback(
            "test_req_1", primary, secondary, tertiary
        )
        assert result == "primary_result"
        assert strategy.get_level() == FallbackLevel.PRIMARY

    @pytest.mark.asyncio
    async def test_primary_fails_secondary_succeeds(self):
        """Verify fallback to secondary on primary failure."""
        strategy = FallbackStrategy()

        async def primary():
            raise RuntimeError("Primary failed")

        async def secondary():
            return "secondary_result"

        async def tertiary():
            raise ValueError("Tertiary should not be called")

        result = await strategy.execute_with_fallback(
            "test_req_2", primary, secondary, tertiary
        )
        assert result == "secondary_result"
        assert strategy.get_level() == FallbackLevel.SECONDARY
        assert strategy._hop_count == 1

    @pytest.mark.asyncio
    async def test_primary_secondary_fail_tertiary_succeeds(self):
        """Verify fallback to tertiary on both primary and secondary failure."""
        strategy = FallbackStrategy()

        async def primary():
            raise RuntimeError("Primary failed")

        async def secondary():
            raise RuntimeError("Secondary failed")

        async def tertiary():
            return "tertiary_result"

        result = await strategy.execute_with_fallback(
            "test_req_3", primary, secondary, tertiary
        )
        assert result == "tertiary_result"
        assert strategy.get_level() == FallbackLevel.TERTIARY
        assert strategy._hop_count == 2

    @pytest.mark.asyncio
    async def test_all_tiers_fail_raises_error(self):
        """Verify FallbackExhaustedError when all tiers fail."""
        strategy = FallbackStrategy()

        async def primary():
            raise RuntimeError("Primary failed")

        async def secondary():
            raise RuntimeError("Secondary failed")

        async def tertiary():
            raise RuntimeError("Tertiary failed")

        with pytest.raises(FallbackExhaustedError):
            await strategy.execute_with_fallback(
                "test_req_4", primary, secondary, tertiary
            )


class TestFallbackStrategyLogicalFlow:
    """Test fallback cascade prevention and flow control."""

    @pytest.mark.asyncio
    async def test_cascade_prevention_honored(self):
        """Verify cascade prevention limits to 2 hops."""
        strategy = FallbackStrategy()
        call_count = {"primary": 0, "secondary": 0, "tertiary": 0}

        async def primary():
            call_count["primary"] += 1
            raise RuntimeError("Primary failed")

        async def secondary():
            call_count["secondary"] += 1
            raise RuntimeError("Secondary failed")

        async def tertiary():
            call_count["tertiary"] += 1
            raise RuntimeError("Tertiary failed")

        with pytest.raises(FallbackExhaustedError):
            await strategy.execute_with_fallback(
                "test_req_5", primary, secondary, tertiary
            )

        assert call_count["primary"] == 1
        assert call_count["secondary"] == 1
        assert call_count["tertiary"] == 1

    @pytest.mark.asyncio
    async def test_non_callable_primary(self):
        """Verify direct value as primary (non-callable)."""
        strategy = FallbackStrategy()

        async def secondary():
            raise ValueError("Should not be called")

        async def tertiary():
            raise ValueError("Should not be called")

        result = await strategy.execute_with_fallback(
            "test_req_6", "primary_value", secondary, tertiary
        )
        assert result == "primary_value"

    @pytest.mark.asyncio
    async def test_non_callable_secondary(self):
        """Verify direct value as secondary (non-callable)."""
        strategy = FallbackStrategy()

        async def primary():
            raise RuntimeError("Primary failed")

        async def tertiary():
            raise ValueError("Should not be called")

        result = await strategy.execute_with_fallback(
            "test_req_7", primary, "secondary_value", tertiary
        )
        assert result == "secondary_value"

    @pytest.mark.asyncio
    async def test_non_callable_tertiary(self):
        """Verify direct value as tertiary (non-callable)."""
        strategy = FallbackStrategy()

        async def primary():
            raise RuntimeError("Primary failed")

        async def secondary():
            raise RuntimeError("Secondary failed")

        result = await strategy.execute_with_fallback(
            "test_req_8", primary, secondary, "tertiary_value"
        )
        assert result == "tertiary_value"


class TestFallbackStrategyStaticMethod:
    """Test static helper method for one-off fallback execution."""

    @pytest.mark.asyncio
    async def test_static_execute_with_fallback(self):
        """Verify static method for one-off execution."""

        async def primary():
            raise RuntimeError("Primary failed")

        async def secondary():
            return "secondary_result"

        async def tertiary():
            raise ValueError("Should not be called")

        result = await FallbackStrategy.execute_async_with_fallback(
            "test_req_9", primary, secondary, tertiary
        )
        assert result == "secondary_result"

    @pytest.mark.asyncio
    async def test_static_execute_all_fail(self):
        """Verify static method raises on all failures."""

        async def primary():
            raise RuntimeError("Primary failed")

        async def secondary():
            raise RuntimeError("Secondary failed")

        async def tertiary():
            raise RuntimeError("Tertiary failed")

        with pytest.raises(FallbackExhaustedError):
            await FallbackStrategy.execute_async_with_fallback(
                "test_req_10", primary, secondary, tertiary
            )
