"""FallbackStrategy — three-tier fallback handler for graceful error recovery."""

import logging
from enum import Enum
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class FallbackLevel(Enum):
    """Fallback hierarchy levels."""

    PRIMARY = 0  # Real adapters (Gemini, Google STT/TTS)
    SECONDARY = 1  # Stub adapters (deterministic responses)
    TERTIARY = 2  # Hardcoded responses (absolute fallback)


class FallbackExhaustedError(Exception):
    """Raised when all fallback levels have been exhausted."""

    pass


class FallbackStrategy:
    """
    Three-tier fallback handler for graceful error recovery.

    Orchestrates cascading fallbacks:
    1. PRIMARY: Try the real adapter (LLM, TTS, STT)
    2. SECONDARY: Fall back to stub adapter
    3. TERTIARY: Fall back to hardcoded response

    Business Rules:
    - Max 2 fallback hops (Primary → Secondary → Tertiary)
    - Track fallback depth per request to prevent infinite cascades
    - Log all fallback transitions for observability
    - If Tertiary fails, raise FallbackExhaustedError
    """

    def __init__(self) -> None:
        """Initialize fallback strategy tracker."""
        self._current_level = FallbackLevel.PRIMARY
        self._hop_count = 0
        self._max_hops = 2

    def increment_depth(self) -> None:
        """
        Increment fallback depth to prevent infinite cascades.

        Raises:
            FallbackExhaustedError: If max hops exceeded
        """
        self._hop_count += 1
        if self._hop_count > self._max_hops:
            raise FallbackExhaustedError(
                f"Fallback cascade exceeded {self._max_hops} hops. Terminating."
            )

    def get_level(self) -> FallbackLevel:
        """Get current fallback level."""
        return self._current_level

    def set_level(self, level: FallbackLevel) -> None:
        """Set current fallback level."""
        self._current_level = level

    def reset(self) -> None:
        """Reset fallback state to primary level."""
        self._current_level = FallbackLevel.PRIMARY
        self._hop_count = 0

    async def execute_with_fallback(
        self,
        request_id: str,
        primary_fn: Callable[..., T],
        secondary_fn: Callable[..., T],
        tertiary_fn: Callable[..., T],
    ) -> T:
        """
        Execute with three-tier fallback strategy.

        Attempts primary, falls back to secondary on error, then tertiary.

        Args:
            request_id: Request identifier for logging
            primary_fn: Primary function (real adapter)
            secondary_fn: Secondary function (stub adapter)
            tertiary_fn: Tertiary function (hardcoded)

        Returns:
            Result from the first successful function

        Raises:
            FallbackExhaustedError: If all tiers fail or max hops exceeded
        """
        current_level = FallbackLevel.PRIMARY

        # Try primary
        try:
            logger.debug(
                "Attempting primary execution request_id=%s", request_id
            )
            result = await primary_fn() if callable(primary_fn) else primary_fn
            logger.info(
                "Primary execution successful request_id=%s", request_id
            )
            return result
        except Exception as e:
            logger.warning(
                "Primary execution failed request_id=%s: %s", request_id, e
            )
            current_level = FallbackLevel.SECONDARY
            self.increment_depth()

        # Try secondary
        try:
            logger.info(
                "Falling back to SECONDARY request_id=%s level=%s",
                request_id,
                FallbackLevel.SECONDARY.name,
            )
            result = await secondary_fn() if callable(secondary_fn) else secondary_fn
            logger.info(
                "Secondary execution successful request_id=%s", request_id
            )
            self._current_level = FallbackLevel.SECONDARY
            return result
        except Exception as e:
            logger.warning(
                "Secondary execution failed request_id=%s: %s", request_id, e
            )
            current_level = FallbackLevel.TERTIARY
            self.increment_depth()

        # Try tertiary
        try:
            logger.info(
                "Falling back to TERTIARY request_id=%s level=%s",
                request_id,
                FallbackLevel.TERTIARY.name,
            )
            result = await tertiary_fn() if callable(tertiary_fn) else tertiary_fn
            logger.info(
                "Tertiary execution successful request_id=%s", request_id
            )
            self._current_level = FallbackLevel.TERTIARY
            return result
        except Exception as e:
            logger.error(
                "Tertiary execution failed request_id=%s: %s (all fallbacks exhausted)",
                request_id,
                e,
            )
            raise FallbackExhaustedError(
                f"All fallback levels exhausted for request {request_id}"
            ) from e

    @staticmethod
    async def execute_async_with_fallback(
        request_id: str,
        primary_fn: Callable[..., T],
        secondary_fn: Callable[..., T],
        tertiary_fn: Callable[..., T],
    ) -> T:
        """
        Static helper for async fallback execution without state tracking.

        Args:
            request_id: Request identifier for logging
            primary_fn: Primary async function
            secondary_fn: Secondary async function
            tertiary_fn: Tertiary async function

        Returns:
            Result from the first successful function

        Raises:
            FallbackExhaustedError: If all tiers fail
        """
        strategy = FallbackStrategy()
        return await strategy.execute_with_fallback(
            request_id, primary_fn, secondary_fn, tertiary_fn
        )
