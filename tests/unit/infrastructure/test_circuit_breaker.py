"""Tests for circuit breaker implementation."""

import asyncio
import pytest
import time

from src.infrastructure.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerManager,
    CircuitState,
)


class TestCircuitBreakerStates:
    """Tests for circuit breaker state transitions."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_starts_closed(self):
        """Circuit breaker starts in CLOSED state."""
        breaker = CircuitBreaker("test", failure_threshold=5, timeout_seconds=1)
        assert breaker.get_state() == "closed"
        assert breaker.get_failure_count() == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_allows_success(self):
        """CLOSED state allows successful calls."""
        breaker = CircuitBreaker("test")

        async def success_func():
            return "success"

        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.get_state() == "closed"

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_allows_single_failure(self):
        """CLOSED state allows calls even after a single failure."""
        breaker = CircuitBreaker("test", failure_threshold=5)

        async def failing_func():
            raise RuntimeError("failure")

        # First failure
        with pytest.raises(RuntimeError):
            await breaker.call(failing_func)

        assert breaker.get_state() == "closed"
        assert breaker.get_failure_count() == 1

        # Second call still allowed
        with pytest.raises(RuntimeError):
            await breaker.call(failing_func)

        assert breaker.get_state() == "closed"

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_threshold(self):
        """Circuit opens after reaching failure threshold."""
        breaker = CircuitBreaker("test", failure_threshold=3)

        async def failing_func():
            raise RuntimeError("failure")

        # Fail 3 times
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(failing_func)

        assert breaker.get_state() == "open"

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_calls(self):
        """OPEN state rejects all calls immediately."""
        breaker = CircuitBreaker("test", failure_threshold=3)

        async def failing_func():
            raise RuntimeError("failure")

        # Open the circuit
        for _ in range(3):
            try:
                await breaker.call(failing_func)
            except RuntimeError:
                pass

        # Subsequent calls are rejected with circuit error
        with pytest.raises(RuntimeError, match="is OPEN"):
            await breaker.call(failing_func)

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_after_timeout(self):
        """Circuit becomes HALF_OPEN after timeout expires."""
        breaker = CircuitBreaker("test", failure_threshold=2, timeout_seconds=0.1)

        async def failing_func():
            raise RuntimeError("failure")

        async def success_func():
            return "success"

        # Open the circuit
        for _ in range(2):
            try:
                await breaker.call(failing_func)
            except RuntimeError:
                pass

        assert breaker.get_state() == "open"

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Next successful call transitions to HALF_OPEN then to CLOSED
        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.get_state() == "closed"

    @pytest.mark.asyncio
    async def test_circuit_breaker_closes_after_recovery(self):
        """HALF_OPEN state closes after successful call."""
        breaker = CircuitBreaker("test", failure_threshold=2, timeout_seconds=0.1)

        async def failing_func():
            raise RuntimeError("failure")

        async def success_func():
            return "success"

        # Open the circuit
        for _ in range(2):
            try:
                await breaker.call(failing_func)
            except RuntimeError:
                pass

        assert breaker.get_state() == "open"

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Recovery succeeds
        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.get_state() == "closed"
        assert breaker.get_failure_count() == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_reopens_on_half_open_failure(self):
        """HALF_OPEN state reopens on failure."""
        breaker = CircuitBreaker("test", failure_threshold=2, timeout_seconds=0.1)

        async def failing_func():
            raise RuntimeError("failure")

        # Open the circuit
        for _ in range(2):
            try:
                await breaker.call(failing_func)
            except RuntimeError:
                pass

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Attempt recovery fails, circuit reopens
        with pytest.raises(RuntimeError):
            await breaker.call(failing_func)

        assert breaker.get_state() == "open"

    @pytest.mark.asyncio
    async def test_circuit_breaker_reset(self):
        """Manual reset closes the circuit."""
        breaker = CircuitBreaker("test", failure_threshold=2)

        async def failing_func():
            raise RuntimeError("failure")

        # Open the circuit
        for _ in range(2):
            try:
                await breaker.call(failing_func)
            except RuntimeError:
                pass

        assert breaker.get_state() == "open"

        # Reset
        await breaker.reset()
        assert breaker.get_state() == "closed"
        assert breaker.get_failure_count() == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_success_resets_failures(self):
        """Successful call in CLOSED state resets failure count."""
        breaker = CircuitBreaker("test", failure_threshold=5)

        async def failing_func():
            raise RuntimeError("failure")

        async def success_func():
            return "success"

        # Fail once
        with pytest.raises(RuntimeError):
            await breaker.call(failing_func)

        assert breaker.get_failure_count() == 1

        # Success resets
        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.get_failure_count() == 0


class TestCircuitBreakerManager:
    """Tests for circuit breaker manager."""

    @pytest.mark.asyncio
    async def test_manager_creates_breaker(self):
        """Manager creates breaker on demand."""
        manager = CircuitBreakerManager()
        breaker = await manager.get_breaker("stt")
        assert breaker is not None
        assert breaker.name == "stt"

    @pytest.mark.asyncio
    async def test_manager_reuses_breaker(self):
        """Manager returns same breaker instance."""
        manager = CircuitBreakerManager()
        breaker1 = await manager.get_breaker("stt")
        breaker2 = await manager.get_breaker("stt")
        assert breaker1 is breaker2

    @pytest.mark.asyncio
    async def test_manager_multiple_breakers(self):
        """Manager maintains separate breakers."""
        manager = CircuitBreakerManager()
        stt_breaker = await manager.get_breaker("stt")
        llm_breaker = await manager.get_breaker("llm")
        tts_breaker = await manager.get_breaker("tts")

        assert stt_breaker is not llm_breaker
        assert llm_breaker is not tts_breaker
        assert stt_breaker.name == "stt"
        assert llm_breaker.name == "llm"
        assert tts_breaker.name == "tts"

    @pytest.mark.asyncio
    async def test_manager_reset_all(self):
        """Manager resets all breakers."""
        manager = CircuitBreakerManager()

        async def failing_func():
            raise RuntimeError("failure")

        # Open all breakers
        for name in ["stt", "llm", "tts"]:
            breaker = await manager.get_breaker(name, failure_threshold=1)
            try:
                await breaker.call(failing_func)
            except RuntimeError:
                pass

        # All are open
        for name in ["stt", "llm", "tts"]:
            breaker = await manager.get_breaker(name)
            assert breaker.get_state() == "open"

        # Reset all
        await manager.reset_all()

        # All are closed
        for name in ["stt", "llm", "tts"]:
            breaker = await manager.get_breaker(name)
            assert breaker.get_state() == "closed"


class TestCircuitBreakerConcurrency:
    """Tests for thread-safe circuit breaker behavior."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_concurrent_calls(self):
        """Circuit breaker handles concurrent calls safely."""
        breaker = CircuitBreaker("test", failure_threshold=10)

        async def success_func(n):
            return n

        # 20 concurrent calls
        tasks = [breaker.call(success_func, i) for i in range(20)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 20
        assert breaker.get_state() == "closed"

    @pytest.mark.asyncio
    async def test_circuit_breaker_concurrent_failures(self):
        """Circuit breaker opens with concurrent failures."""
        breaker = CircuitBreaker("test", failure_threshold=5)

        async def failing_func(n):
            raise RuntimeError(f"failure {n}")

        # 10 concurrent failures
        tasks = [breaker.call(failing_func, i) for i in range(10)]

        with pytest.raises(RuntimeError):
            await asyncio.gather(*tasks)

        # Should be open or opening
        assert breaker.get_failure_count() >= 5
