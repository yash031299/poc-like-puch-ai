"""Circuit breaker for API calls — prevents cascading failures."""

import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"          # Normal operation, requests pass through
    OPEN = "open"              # Failing, requests are rejected
    HALF_OPEN = "half_open"    # Testing recovery, one request allowed


class CircuitBreaker:
    """
    Circuit breaker pattern implementation for fault tolerance.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failure threshold exceeded, requests are immediately rejected
    - HALF_OPEN: Testing if service recovered, one request is allowed
    
    Transitions:
    - CLOSED → OPEN: When failure_threshold consecutive failures occur
    - OPEN → HALF_OPEN: After timeout_seconds have elapsed
    - HALF_OPEN → CLOSED: When test request succeeds
    - HALF_OPEN → OPEN: When test request fails
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 5,
        recovery_timeout_seconds: int = 5,
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Circuit breaker name (for logging)
            failure_threshold: Number of consecutive failures before opening (default 5)
            timeout_seconds: Seconds to wait before attempting recovery (default 5)
            recovery_timeout_seconds: Seconds to wait before testing recovery (default 5)
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.recovery_timeout_seconds = recovery_timeout_seconds

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._recovery_attempt_time: Optional[float] = None
        self._lock = asyncio.Lock()

        logger.info(
            f"CircuitBreaker '{name}' initialized: "
            f"failure_threshold={failure_threshold}, timeout={timeout_seconds}s"
        )

    async def call(
        self,
        func: Callable,
        *args,
        **kwargs,
    ):
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to call
            *args, **kwargs: Arguments to pass to func

        Returns:
            Result of func() if successful

        Raises:
            RuntimeError: If circuit is open or function fails
        """
        async with self._lock:
            state = self._state
            logger.debug(f"CircuitBreaker '{self.name}': {state.value}")

            if state == CircuitState.OPEN:
                # Check if recovery timeout has elapsed
                if self._should_attempt_recovery():
                    logger.info(f"CircuitBreaker '{self.name}': attempting recovery (HALF_OPEN)")
                    self._state = CircuitState.HALF_OPEN
                    self._recovery_attempt_time = time.time()
                else:
                    # Still in failure timeout period
                    raise RuntimeError(
                        f"CircuitBreaker '{self.name}' is OPEN. Service unavailable."
                    )

        # Call the function
        try:
            result = await func(*args, **kwargs)
            # Success!
            async with self._lock:
                if self._state == CircuitState.HALF_OPEN:
                    # Recovery succeeded!
                    logger.info(f"CircuitBreaker '{self.name}': recovery successful (CLOSED)")
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                elif self._state == CircuitState.CLOSED:
                    # Normal success, reset failures
                    self._failure_count = 0
            return result
        except Exception as exc:
            # Failure!
            async with self._lock:
                self._record_failure()
            raise

    def _record_failure(self) -> None:
        """Record a failure and update circuit state."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                f"CircuitBreaker '{self.name}': failure threshold reached ({self._failure_count}). "
                f"Opening circuit."
            )
        else:
            logger.debug(
                f"CircuitBreaker '{self.name}': failure {self._failure_count}/{self.failure_threshold}"
            )

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has elapsed to attempt recovery."""
        if not self._last_failure_time:
            return False
        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.timeout_seconds

    def get_state(self) -> str:
        """Get current circuit state as string."""
        return self._state.value

    def get_failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    async def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        async with self._lock:
            logger.info(f"CircuitBreaker '{self.name}': manually reset to CLOSED")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None


class CircuitBreakerManager:
    """Manages multiple circuit breakers for different services."""

    def __init__(self):
        """Initialize circuit breaker manager."""
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 5,
    ) -> CircuitBreaker:
        """
        Get or create a circuit breaker.

        Args:
            name: Breaker name (e.g., 'stt', 'llm', 'tts')
            failure_threshold: Failures before opening
            timeout_seconds: Recovery timeout

        Returns:
            CircuitBreaker instance
        """
        async with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    timeout_seconds=timeout_seconds,
                )
            return self._breakers[name]

    async def reset_all(self) -> None:
        """Reset all circuit breakers."""
        async with self._lock:
            for breaker in self._breakers.values():
                await breaker.reset()
            logger.info("All circuit breakers reset")
