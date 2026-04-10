"""TimeoutHandler — async timeout management with fallback support."""

import asyncio
import logging
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TimeoutError(Exception):
    """Raised when an operation exceeds timeout."""

    pass


class TimeoutHandler:
    """
    Async timeout handler with fallback support.

    Enforces configurable timeouts on operations and delegates to
    fallback functions when timeouts occur.

    Timeout recommendations:
    - LLM: 5 seconds (token generation)
    - TTS: 3 seconds (audio synthesis)
    - STT: 10 seconds (transcription)
    """

    @staticmethod
    async def with_timeout(
        coro,
        timeout_ms: int,
        operation_name: str = "operation",
        fallback_fn: Optional[Callable[..., T]] = None,
    ) -> T:
        """
        Execute a coroutine with timeout and optional fallback.

        Args:
            coro: The coroutine to execute
            timeout_ms: Timeout in milliseconds
            operation_name: Name of operation for logging
            fallback_fn: Fallback function to call on timeout (optional)

        Returns:
            Result from coroutine or fallback function

        Raises:
            asyncio.TimeoutError: If no fallback and timeout exceeded
        """
        timeout_sec = timeout_ms / 1000.0

        try:
            logger.debug(
                "Executing with timeout operation=%s timeout_ms=%d",
                operation_name,
                timeout_ms,
            )
            result = await asyncio.wait_for(coro, timeout=timeout_sec)
            logger.debug(
                "Operation completed within timeout operation=%s",
                operation_name,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "Operation timeout operation=%s timeout_ms=%d",
                operation_name,
                timeout_ms,
            )
            if fallback_fn:
                logger.info(
                    "Executing fallback function operation=%s",
                    operation_name,
                )
                try:
                    result = await fallback_fn() if callable(fallback_fn) else fallback_fn
                    logger.info(
                        "Fallback executed successfully operation=%s",
                        operation_name,
                    )
                    return result
                except Exception as e:
                    logger.error(
                        "Fallback execution failed operation=%s: %s",
                        operation_name,
                        e,
                    )
                    raise
            else:
                logger.error(
                    "No fallback available for timeout operation=%s",
                    operation_name,
                )
                raise asyncio.TimeoutError(
                    f"Operation '{operation_name}' exceeded timeout {timeout_ms}ms"
                )

    @staticmethod
    async def with_timeout_and_default(
        coro,
        timeout_ms: int,
        default_value: T,
        operation_name: str = "operation",
    ) -> T:
        """
        Execute a coroutine with timeout, returning default on timeout.

        Args:
            coro: The coroutine to execute
            timeout_ms: Timeout in milliseconds
            default_value: Value to return if timeout occurs
            operation_name: Name of operation for logging

        Returns:
            Result from coroutine or default value
        """
        timeout_sec = timeout_ms / 1000.0

        try:
            logger.debug(
                "Executing with timeout operation=%s timeout_ms=%d",
                operation_name,
                timeout_ms,
            )
            result = await asyncio.wait_for(coro, timeout=timeout_sec)
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "Operation timeout, using default operation=%s timeout_ms=%d",
                operation_name,
                timeout_ms,
            )
            return default_value

    @staticmethod
    def get_safe_timeout(timeout_ms: int, min_ms: int = 100) -> float:
        """
        Get a safe timeout value, ensuring minimum threshold.

        Args:
            timeout_ms: Requested timeout in milliseconds
            min_ms: Minimum timeout to allow (default 100ms)

        Returns:
            Safe timeout in seconds
        """
        safe_ms = max(timeout_ms, min_ms)
        return safe_ms / 1000.0

    @staticmethod
    async def execute_with_deadline(
        coro,
        deadline_sec: float,
        operation_name: str = "operation",
    ) -> T:
        """
        Execute with an absolute deadline timestamp.

        Args:
            coro: The coroutine to execute
            deadline_sec: Absolute deadline (seconds since epoch)
            operation_name: Name of operation for logging

        Returns:
            Coroutine result

        Raises:
            asyncio.TimeoutError: If deadline exceeded
        """
        now = asyncio.get_event_loop().time()
        timeout = deadline_sec - now

        if timeout <= 0:
            raise asyncio.TimeoutError(
                f"Deadline already passed for operation '{operation_name}'"
            )

        logger.debug(
            "Executing with deadline operation=%s timeout_sec=%.2f",
            operation_name,
            timeout,
        )

        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "Operation exceeded deadline operation=%s timeout_sec=%.2f",
                operation_name,
                timeout,
            )
            raise
