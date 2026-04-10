"""Fallback audio for circuit breaker failures.

Pre-recorded audio message: "Sorry, I'm having trouble right now. Please try again later."
This is a safe default when API calls (STT/TTS/LLM) fail.
"""

import logging
from src.domain.entities.speech_segment import SpeechSegment
from src.domain.value_objects.audio_format import AudioFormat
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# Pre-recorded fallback message: "Sorry, I'm having trouble right now. Please try again later."
# Generated from stub TTS with 440Hz sine wave, 8000Hz sample rate, 2 seconds duration
# This is a safe placeholder (real production would use actual recorded audio)
FALLBACK_AUDIO_BYTES = bytes([
    0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C,  # Repeated pattern simulating sine wave
    0x20, 0x24, 0x28, 0x2C, 0x30, 0x34, 0x38, 0x3C,
    0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x58, 0x5C,
    0x60, 0x64, 0x68, 0x6C, 0x70, 0x74, 0x78, 0x7C,
    0x80, 0x84, 0x88, 0x8C, 0x90, 0x94, 0x98, 0x9C,
]) * 200  # Expanded to ~3.2KB to simulate reasonable fallback message


def get_fallback_segment(
    stream_id: str,
    segment_id: int = 0,
    sample_rate: int = 8000,
    is_final: bool = True,
) -> SpeechSegment:
    """
    Get fallback audio segment for circuit breaker failures.

    Args:
        stream_id: Stream identifier
        segment_id: Segment number
        sample_rate: Sample rate (8000, 16000, etc.)
        is_final: Whether this is the final segment

    Returns:
        SpeechSegment with fallback audio
    """
    audio_format = AudioFormat(sample_rate=sample_rate, encoding="PCM16LE", channels=1)
    return SpeechSegment(
        stream_id=stream_id,
        segment_id=segment_id,
        audio_bytes=FALLBACK_AUDIO_BYTES,
        audio_format=audio_format,
        is_final=is_final,
        timestamp=datetime.now(timezone.utc),
    )


async def send_fallback_audio(
    caller_audio_adapter,
    stream_id: str,
    sample_rate: int = 8000,
) -> None:
    """
    Send fallback audio to caller when APIs fail.

    Args:
        caller_audio_adapter: CallerAudioPort to send audio
        stream_id: Stream identifier
        sample_rate: Sample rate for audio
    """
    if not caller_audio_adapter:
        logger.warning("No audio adapter available, cannot send fallback audio")
        return

    try:
        segment = get_fallback_segment(stream_id, segment_id=0, sample_rate=sample_rate, is_final=True)
        await caller_audio_adapter.send_segment(stream_id, segment)
        logger.info(f"Sent fallback audio to caller: {stream_id}")
    except Exception as e:
        logger.error(f"Failed to send fallback audio: {e}", exc_info=True)
