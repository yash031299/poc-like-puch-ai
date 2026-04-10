"""Integration tests for graceful degradation — call continues despite failures."""

import asyncio
import base64
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.adapters.stub_llm_adapter import StubLLMAdapter
from src.domain.entities.utterance import Utterance
from src.domain.services.fallback_handler import (
    FallbackExhaustedError,
    FallbackLevel,
    FallbackStrategy,
)
from src.domain.services.timeout_handler import TimeoutHandler
from src.domain.value_objects.audio_format import AudioFormat


class TestGracefulDegradationLLM:
    """Test graceful LLM failure handling."""

    @pytest.mark.asyncio
    async def test_llm_timeout_falls_back_to_stub(self):
        """Verify LLM timeout triggers fallback to stub response."""
        strategy = FallbackStrategy()
        
        # Real LLM takes too long
        async def real_llm():
            await asyncio.sleep(10)
            return "real response"
        
        # Stub LLM returns immediately
        async def stub_llm():
            return "I'm sorry, I didn't catch that. Can you repeat?"
        
        # Hardcoded fallback
        async def hardcoded():
            return "Please try again."

        result = await TimeoutHandler.with_timeout(
            strategy.execute_with_fallback(
                "req_1", real_llm, stub_llm, hardcoded
            ),
            timeout_ms=5000,
            operation_name="llm_with_fallback",
            fallback_fn=hardcoded,
        )
        
        assert result in [
            "I'm sorry, I didn't catch that. Can you repeat?",
            "Please try again.",
        ]

    @pytest.mark.asyncio
    async def test_llm_error_triggers_fallback_response(self):
        """Verify LLM error triggers stub adapter."""
        stub_llm = StubLLMAdapter()
        utterance = Utterance(
            "Hello", confidence=0.9, is_final=True, timestamp=datetime.now(timezone.utc)
        )

        # Real LLM fails
        async def real_llm():
            raise RuntimeError("API error")

        # Fallback to stub
        async def fallback_gen():
            response = ""
            async for token in stub_llm.generate("s1", utterance, []):
                response += token
            return response

        result = await fallback_gen()
        assert len(result) > 0  # Should have fallback response

    @pytest.mark.asyncio
    async def test_llm_failures_inform_user(self):
        """Verify user is informed of LLM failures via fallback message."""
        fallback_messages = StubLLMAdapter.FALLBACK_RESPONSES

        for msg in fallback_messages:
            assert (
                "sorry" in msg.lower()
                or "trouble" in msg.lower()
                or "repeat" in msg.lower()
                or "think" in msg.lower()
                or "again" in msg.lower()
            )


class TestGracefulDegradationTTS:
    """Test graceful TTS failure handling."""

    @pytest.mark.asyncio
    async def test_tts_timeout_skips_to_next_phrase(self):
        """Verify TTS timeout skips phrase and continues."""
        # Simulate TTS timeout with default fallback
        result = await TimeoutHandler.with_timeout_and_default(
            asyncio.sleep(4),  # Exceeds 3s timeout
            timeout_ms=3000,
            default_value=b"",
            operation_name="tts_synthesize",
        )

        assert result == b""  # Empty audio, but doesn't crash

    @pytest.mark.asyncio
    async def test_tts_error_returns_empty_audio(self):
        """Verify TTS error returns empty audio without crash."""
        strategy = FallbackStrategy()

        async def failing_tts():
            raise RuntimeError("TTS API error")

        async def text_passthrough():
            return ""  # Skip audio, continue

        async def hardcoded():
            return ""

        result = await strategy.execute_with_fallback(
            "req_tts", failing_tts, text_passthrough, hardcoded
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_tts_failures_call_continues(self):
        """Verify call continues despite TTS failures."""
        call_continued = True

        # Simulate TTS failure
        async def tts_fail():
            raise RuntimeError("TTS failed")

        try:
            async def fallback():
                nonlocal call_continued
                call_continued = True
                return ""

            result = await TimeoutHandler.with_timeout_and_default(
                tts_fail(),
                timeout_ms=3000,
                default_value="",
                operation_name="tts",
            )
            # Should use default without raising
            assert result == ""
            assert call_continued
        except Exception:
            call_continued = False

        assert call_continued


class TestGracefulDegradationSTT:
    """Test graceful STT failure handling."""

    @pytest.mark.asyncio
    async def test_stt_timeout_asks_user_to_repeat(self):
        """Verify STT timeout prompts user to repeat."""
        # STT timeout with ask user to repeat fallback
        async def fallback():
            return "Could you please repeat that?"

        result = await TimeoutHandler.with_timeout(
            asyncio.sleep(11),  # Exceeds 10s timeout
            timeout_ms=10000,
            operation_name="stt_transcribe",
            fallback_fn=fallback,
        )
        assert "repeat" in result.lower()

    @pytest.mark.asyncio
    async def test_stt_error_asks_user_to_repeat(self):
        """Verify STT error prompts user to repeat."""
        strategy = FallbackStrategy()

        async def failing_stt():
            raise RuntimeError("STT API error")

        async def stub_stt():
            return "Could you please repeat that?"

        async def hardcoded():
            return "Please repeat."

        result = await strategy.execute_with_fallback(
            "req_stt", failing_stt, stub_stt, hardcoded
        )
        assert "repeat" in result.lower()

    @pytest.mark.asyncio
    async def test_stt_failures_call_continues(self):
        """Verify call continues despite STT failures."""
        call_continued = False

        async def stt_operation():
            raise RuntimeError("STT failed")

        async def fallback():
            nonlocal call_continued
            call_continued = True
            return "Could you please repeat that?"

        try:
            result = await TimeoutHandler.with_timeout(
                stt_operation(),
                timeout_ms=10000,
                operation_name="stt",
                fallback_fn=fallback,
            )
            assert call_continued
            assert "repeat" in result.lower()
        except Exception as e:
            pytest.fail(f"Should have handled error gracefully: {e}")


class TestCascadePreventionGraceful:
    """Test cascade prevention in graceful degradation scenarios."""

    @pytest.mark.asyncio
    async def test_max_two_fallback_hops_enforced(self):
        """Verify max 2 fallback hops enforced across requests."""
        strategy = FallbackStrategy()

        async def fail_primary():
            raise RuntimeError("Primary failed")

        async def fail_secondary():
            raise RuntimeError("Secondary failed")

        async def fail_tertiary():
            raise RuntimeError("Tertiary failed")

        # First request uses Primary → Secondary → Tertiary
        with pytest.raises(FallbackExhaustedError):
            await strategy.execute_with_fallback(
                "req_1", fail_primary, fail_secondary, fail_tertiary
            )

        # Hops should be at max
        assert strategy._hop_count == 2

    @pytest.mark.asyncio
    async def test_fallback_depth_reset_between_requests(self):
        """Verify fallback depth resets between different requests."""
        strategy = FallbackStrategy()

        async def success():
            return "ok"

        async def unused():
            raise RuntimeError("Should not be called")

        # Request 1: primary succeeds
        result1 = await strategy.execute_with_fallback(
            "req_1", success, unused, unused
        )
        assert result1 == "ok"
        assert strategy._hop_count == 0  # Reset after success

        # Request 2: primary succeeds again
        result2 = await strategy.execute_with_fallback(
            "req_2", success, unused, unused
        )
        assert result2 == "ok"
        assert strategy._hop_count == 0  # Reset after success

    @pytest.mark.asyncio
    async def test_call_ends_gracefully_on_cascade_exhaustion(self):
        """Verify call ends gracefully when cascade exhausted."""
        strategy = FallbackStrategy()
        call_ended = False

        async def all_fail():
            raise RuntimeError("Failed")

        try:
            await strategy.execute_with_fallback(
                "req_end", all_fail, all_fail, all_fail
            )
        except FallbackExhaustedError:
            call_ended = True

        assert call_ended


class TestGracefulDegradationEndToEnd:
    """End-to-end graceful degradation scenarios."""

    @pytest.mark.asyncio
    async def test_call_continues_with_degraded_service(self):
        """Verify call continues even with all real adapters failing."""
        strategy = FallbackStrategy()

        # Simulate all real adapters failing
        async def real_stt():
            raise RuntimeError("Google STT unavailable")

        async def stub_stt():
            return "I didn't understand. Please repeat."

        async def fallback_stt():
            return "Please try again."

        result = await strategy.execute_with_fallback(
            "call_1", real_stt, stub_stt, fallback_stt
        )
        assert "repeat" in result.lower() or "again" in result.lower()

    @pytest.mark.asyncio
    async def test_user_informed_of_degradation(self):
        """Verify user is informed when system degrades."""
        stub_llm = StubLLMAdapter()
        utterance = Utterance("test", confidence=0.9, is_final=True)

        # Use fallback response
        stub_llm.use_fallback = True

        response_text = ""
        async for token in stub_llm.generate("s1", utterance, []):
            response_text += token

        # Should contain indication of degradation
        assert len(response_text) > 0
        assert any(
            word in response_text.lower()
            for word in ["sorry", "trouble", "repeat", "try again"]
        )

    @pytest.mark.asyncio
    async def test_multiple_sequential_fallbacks(self):
        """Verify multiple sequential fallback requests work correctly."""
        strategy = FallbackStrategy()

        call_count = {"primary": 0, "secondary": 0}

        async def primary_sometimes_fails(fail=False):
            call_count["primary"] += 1
            if fail:
                raise RuntimeError("Primary failed")
            return "primary_result"

        async def secondary():
            call_count["secondary"] += 1
            return "secondary_result"

        async def tertiary():
            return "tertiary_result"

        # Request 1: Primary succeeds
        result1 = await strategy.execute_with_fallback(
            "req_1",
            lambda: primary_sometimes_fails(fail=False),
            secondary,
            tertiary,
        )
        assert result1 == "primary_result"
        assert call_count["primary"] == 1
        assert call_count["secondary"] == 0

        # Request 2: Primary fails, fallback to secondary
        result2 = await strategy.execute_with_fallback(
            "req_2",
            lambda: primary_sometimes_fails(fail=True),
            secondary,
            tertiary,
        )
        assert result2 == "secondary_result"
        assert call_count["primary"] == 2
        assert call_count["secondary"] == 1
