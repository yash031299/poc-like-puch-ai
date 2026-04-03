"""Integration tests for VAD + ProcessAudioUseCase."""

import pytest
from datetime import datetime, timezone

from src.adapters.in_memory_session_repository import InMemorySessionRepository
from src.adapters.stub_stt_adapter import StubSTTAdapter
from src.adapters.webrtc_vad_adapter import WebRTCVADAdapter
from src.domain.entities.audio_chunk import AudioChunk
from src.domain.services.audio_buffer_manager import AudioBufferManager
from src.domain.value_objects.audio_format import AudioFormat
from src.use_cases.accept_call import AcceptCallUseCase
from src.use_cases.process_audio import ProcessAudioUseCase


def create_silence_chunk(seq: int, sample_rate: int = 16000) -> AudioChunk:
    """Create a silent audio chunk (20ms)."""
    audio_format = AudioFormat(sample_rate=sample_rate, encoding="PCM16LE", channels=1)
    num_bytes = int((sample_rate * 20 / 1000) * 2)
    return AudioChunk(
        sequence_number=seq + 1,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=b"\x00" * num_bytes
    )


@pytest.mark.asyncio
async def test_vad_reduces_stt_calls():
    """Test that VAD reduces STT calls by buffering audio."""
    # Setup
    repo = InMemorySessionRepository()
    stt = StubSTTAdapter(transcript="Hello world", trigger_every=1)
    vad = WebRTCVADAdapter(sensitivity=2)
    buffer_manager = AudioBufferManager(vad, silence_threshold_ms=100)
    
    # Create use cases
    accept_uc = AcceptCallUseCase(session_repo=repo)
    process_uc = ProcessAudioUseCase(
        session_repo=repo,
        stt=stt,
        buffer_manager=buffer_manager
    )
    
    # Accept call
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    await accept_uc.execute(
        stream_id="test-stream",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format,
    )
    
    # Send multiple silence chunks (should be discarded, not processed)
    for i in range(5):
        chunk = create_silence_chunk(i)
        utterances = await process_uc.execute("test-stream", chunk)
        
        # With VAD, silence chunks should not trigger STT
        # (they stay in IDLE state and are discarded)
        assert len(utterances) == 0
    
    # Verify buffer metrics
    metrics = buffer_manager.get_metrics("test-stream")
    assert metrics["state"] == "idle"  # Still in IDLE (no speech detected)
    assert metrics["buffer_size"] == 0  # No buffering for silence


@pytest.mark.asyncio
async def test_process_audio_without_vad_legacy_behavior():
    """Test that without VAD, every chunk is processed (legacy behavior)."""
    # Setup WITHOUT buffer manager
    repo = InMemorySessionRepository()
    stt = StubSTTAdapter(transcript="Hello world", trigger_every=1)
    
    process_uc = ProcessAudioUseCase(
        session_repo=repo,
        stt=stt,
        buffer_manager=None  # No VAD
    )
    
    # Accept call
    accept_uc = AcceptCallUseCase(session_repo=repo)
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    await accept_uc.execute(
        stream_id="test-stream",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format,
    )
    
    # Send chunks - should process every one
    chunk = create_silence_chunk(1)
    utterances = await process_uc.execute("test-stream", chunk)
    
    # Without VAD, STT is called on every chunk
    assert len(utterances) > 0  # STT triggered immediately


@pytest.mark.asyncio
async def test_vad_integration_end_to_end():
    """Test complete VAD integration flow."""
    repo = InMemorySessionRepository()
    stt = StubSTTAdapter(transcript="Test message", trigger_every=1)
    vad = WebRTCVADAdapter(sensitivity=2)
    buffer_manager = AudioBufferManager(vad, silence_threshold_ms=200)
    
    process_uc = ProcessAudioUseCase(
        session_repo=repo,
        stt=stt,
        buffer_manager=buffer_manager
    )
    
    # Accept call
    accept_uc = AcceptCallUseCase(session_repo=repo)
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    await accept_uc.execute(
        stream_id="stream-1",
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=audio_format,
    )
    
    # Process silence chunks
    for i in range(3):
        await process_uc.execute("stream-1", create_silence_chunk(i))
    
    # Verify metrics
    metrics = buffer_manager.get_metrics("stream-1")
    assert metrics["chunks_buffered"] == 0  # Silence not buffered
    assert metrics["flushes_count"] == 0  # No flushes yet


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
