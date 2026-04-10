"""Tests for TimeoutHandler — async timeout with fallback support."""

import asyncio

import pytest

from src.domain.services.timeout_handler import TimeoutHandler


class TestTimeoutHandlerWithTimeout:
    """Test basic timeout functionality."""

    @pytest.mark.asyncio
    async def test_completes_within_timeout(self):
        """Verify operation completes when under timeout."""

        async def fast_operation():
            await asyncio.sleep(0.01)
            return "success"

        result = await TimeoutHandler.with_timeout(
            fast_operation(), timeout_ms=1000, operation_name="fast_op"
        )
        assert result == "success"

    @pytest.mark.asyncio
    async def test_timeout_exceeds_limit(self):
        """Verify asyncio.TimeoutError when operation exceeds timeout."""

        async def slow_operation():
            await asyncio.sleep(1.0)
            return "success"

        with pytest.raises(asyncio.TimeoutError):
            await TimeoutHandler.with_timeout(
                slow_operation(), timeout_ms=100, operation_name="slow_op"
            )

    @pytest.mark.asyncio
    async def test_timeout_with_fallback_on_timeout(self):
        """Verify fallback called when timeout occurs."""

        async def slow_operation():
            await asyncio.sleep(1.0)
            return "success"

        async def fallback():
            return "fallback_result"

        result = await TimeoutHandler.with_timeout(
            slow_operation(),
            timeout_ms=100,
            operation_name="slow_op",
            fallback_fn=fallback,
        )
        assert result == "fallback_result"

    @pytest.mark.asyncio
    async def test_timeout_with_fallback_no_timeout(self):
        """Verify fallback not called when operation succeeds."""

        async def fast_operation():
            await asyncio.sleep(0.01)
            return "success"

        async def fallback():
            raise RuntimeError("Fallback should not be called")

        result = await TimeoutHandler.with_timeout(
            fast_operation(),
            timeout_ms=1000,
            operation_name="fast_op",
            fallback_fn=fallback,
        )
        assert result == "success"

    @pytest.mark.asyncio
    async def test_timeout_with_fallback_failure(self):
        """Verify fallback failure is propagated."""

        async def slow_operation():
            await asyncio.sleep(1.0)
            return "success"

        async def fallback():
            raise RuntimeError("Fallback failed")

        with pytest.raises(RuntimeError):
            await TimeoutHandler.with_timeout(
                slow_operation(),
                timeout_ms=100,
                operation_name="slow_op",
                fallback_fn=fallback,
            )


class TestTimeoutHandlerWithDefault:
    """Test timeout with default value return."""

    @pytest.mark.asyncio
    async def test_returns_default_on_timeout(self):
        """Verify default value returned when timeout occurs."""

        async def slow_operation():
            await asyncio.sleep(1.0)
            return "success"

        result = await TimeoutHandler.with_timeout_and_default(
            slow_operation(),
            timeout_ms=100,
            default_value="default_result",
            operation_name="slow_op",
        )
        assert result == "default_result"

    @pytest.mark.asyncio
    async def test_returns_actual_result_no_timeout(self):
        """Verify actual result returned when within timeout."""

        async def fast_operation():
            await asyncio.sleep(0.01)
            return "actual_result"

        result = await TimeoutHandler.with_timeout_and_default(
            fast_operation(),
            timeout_ms=1000,
            default_value="default_result",
            operation_name="fast_op",
        )
        assert result == "actual_result"

    @pytest.mark.asyncio
    async def test_default_value_types(self):
        """Verify default value works with different types."""
        async def slow_operation():
            await asyncio.sleep(1.0)
            return []

        # Test with None
        result = await TimeoutHandler.with_timeout_and_default(
            slow_operation(), timeout_ms=100, default_value=None, operation_name="op"
        )
        assert result is None

        # Test with empty list
        result = await TimeoutHandler.with_timeout_and_default(
            slow_operation(), timeout_ms=100, default_value=[], operation_name="op"
        )
        assert result == []

        # Test with empty string
        result = await TimeoutHandler.with_timeout_and_default(
            slow_operation(), timeout_ms=100, default_value="", operation_name="op"
        )
        assert result == ""


class TestTimeoutHandlerSafeTimeout:
    """Test safe timeout calculation."""

    def test_safe_timeout_below_minimum(self):
        """Verify minimum threshold enforced."""
        result = TimeoutHandler.get_safe_timeout(50, min_ms=100)
        assert result == 0.1  # 100ms / 1000

    def test_safe_timeout_above_minimum(self):
        """Verify value used when above minimum."""
        result = TimeoutHandler.get_safe_timeout(500, min_ms=100)
        assert result == 0.5  # 500ms / 1000

    def test_safe_timeout_custom_minimum(self):
        """Verify custom minimum threshold."""
        result = TimeoutHandler.get_safe_timeout(200, min_ms=300)
        assert result == 0.3  # 300ms / 1000

    def test_safe_timeout_zero(self):
        """Verify zero timeout enforces minimum."""
        result = TimeoutHandler.get_safe_timeout(0, min_ms=100)
        assert result == 0.1  # 100ms / 1000


class TestTimeoutHandlerDeadline:
    """Test absolute deadline execution."""

    @pytest.mark.asyncio
    async def test_execute_with_deadline_success(self):
        """Verify operation completes before deadline."""

        async def fast_operation():
            await asyncio.sleep(0.01)
            return "success"

        loop = asyncio.get_event_loop()
        deadline = loop.time() + 1.0  # 1 second in future

        result = await TimeoutHandler.execute_with_deadline(
            fast_operation(), deadline, operation_name="op"
        )
        assert result == "success"

    @pytest.mark.asyncio
    async def test_execute_with_deadline_exceeded(self):
        """Verify timeout error when deadline exceeded."""

        async def slow_operation():
            await asyncio.sleep(1.0)
            return "success"

        loop = asyncio.get_event_loop()
        deadline = loop.time() + 0.1  # 100ms in future

        with pytest.raises(asyncio.TimeoutError):
            await TimeoutHandler.execute_with_deadline(
                slow_operation(), deadline, operation_name="op"
            )

    @pytest.mark.asyncio
    async def test_execute_with_deadline_already_passed(self):
        """Verify error when deadline already passed."""

        async def operation():
            return "success"

        loop = asyncio.get_event_loop()
        deadline = loop.time() - 1.0  # 1 second in past

        with pytest.raises(asyncio.TimeoutError):
            await TimeoutHandler.execute_with_deadline(
                operation(), deadline, operation_name="op"
            )


class TestTimeoutHandlerIntegration:
    """Integration tests for timeout scenarios."""

    @pytest.mark.asyncio
    async def test_llm_timeout_scenario(self):
        """Simulate LLM timeout (recommended 5s timeout)."""

        async def llm_generate():
            await asyncio.sleep(6.0)  # Exceeds 5s
            return "token"

        async def llm_fallback():
            return "I'm sorry, I didn't catch that. Can you repeat?"

        result = await TimeoutHandler.with_timeout(
            llm_generate(),
            timeout_ms=5000,
            operation_name="llm_generate",
            fallback_fn=llm_fallback,
        )
        assert "sorry" in result.lower() or "repeat" in result.lower()

    @pytest.mark.asyncio
    async def test_tts_timeout_scenario(self):
        """Simulate TTS timeout (recommended 3s timeout)."""

        async def tts_synthesize():
            await asyncio.sleep(4.0)  # Exceeds 3s
            return b"audio_data"

        result = await TimeoutHandler.with_timeout_and_default(
            tts_synthesize(),
            timeout_ms=3000,
            default_value=b"",
            operation_name="tts_synthesize",
        )
        assert result == b""

    @pytest.mark.asyncio
    async def test_stt_timeout_scenario(self):
        """Simulate STT timeout (recommended 10s timeout)."""

        async def stt_transcribe():
            await asyncio.sleep(11.0)  # Exceeds 10s
            return "transcribed text"

        async def stt_fallback():
            return "Could you please repeat that?"

        result = await TimeoutHandler.with_timeout(
            stt_transcribe(),
            timeout_ms=10000,
            operation_name="stt_transcribe",
            fallback_fn=stt_fallback,
        )
        assert "repeat" in result.lower()
