"""Integration tests for UC-002: Process Caller Audio.

Verifies Gherkin scenarios from features/UC-002-process-caller-audio.feature
"""

import pytest
from datetime import datetime, timezone


def test_uc002_receive_and_process_single_audio_chunk() -> None:
    """
    Integration test for UC-002 first scenario.
    
    Scenario: Receive and process single audio chunk
      Given the caller is connected
      When an audio chunk arrives from the telephony provider
      Then the system creates an AudioChunk entity
      And the AudioChunk has a sequence number
      And the AudioChunk has a timestamp
      And the AudioChunk is added to the ConversationSession
      And the audio is queued for transcription
    """
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.audio_chunk import AudioChunk
    
    # Given the caller is connected
    stream_id = StreamIdentifier("stream-abc-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    conversation.activate()  # Activate the call
    
    # When an audio chunk arrives from the telephony provider
    timestamp = datetime.now(timezone.utc)
    audio_data = bytes(3200)  # 0.1 second of audio at 16kHz PCM16LE
    
    chunk = AudioChunk(
        sequence_number=1,
        timestamp=timestamp,
        audio_format=audio_format,
        audio_data=audio_data
    )
    
    # Then the system creates an AudioChunk entity
    assert chunk is not None
    assert isinstance(chunk, AudioChunk)
    
    # And the AudioChunk has a sequence number
    assert chunk.sequence_number == 1
    
    # And the AudioChunk has a timestamp
    assert chunk.timestamp == timestamp
    
    # And the AudioChunk is added to the ConversationSession
    conversation.add_audio_chunk(chunk)
    assert len(conversation.audio_chunks) == 1
    assert conversation.audio_chunks[0] == chunk


def test_uc002_process_multiple_audio_chunks_in_sequence() -> None:
    """
    Integration test for UC-002 second scenario.
    
    Scenario: Process multiple audio chunks in sequence
      Given the caller is speaking
      When audio chunks arrive with sequence numbers 1, 2, 3
      Then the system processes chunks in order
      And each chunk is timestamped correctly
      And chunks are accumulated for transcription
    """
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.audio_chunk import AudioChunk
    
    # Given the caller is speaking
    stream_id = StreamIdentifier("stream-123")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    conversation.activate()
    
    # When audio chunks arrive with sequence numbers 1, 2, 3
    timestamps = []
    for seq in [1, 2, 3]:
        timestamp = datetime.now(timezone.utc)
        timestamps.append(timestamp)
        
        chunk = AudioChunk(
            sequence_number=seq,
            timestamp=timestamp,
            audio_format=audio_format,
            audio_data=bytes(1600)  # 0.05s of audio
        )
        conversation.add_audio_chunk(chunk)
    
    # Then the system processes chunks in order
    assert len(conversation.audio_chunks) == 3
    assert conversation.audio_chunks[0].sequence_number == 1
    assert conversation.audio_chunks[1].sequence_number == 2
    assert conversation.audio_chunks[2].sequence_number == 3
    
    # And each chunk is timestamped correctly
    assert conversation.audio_chunks[0].timestamp == timestamps[0]
    assert conversation.audio_chunks[1].timestamp == timestamps[1]
    assert conversation.audio_chunks[2].timestamp == timestamps[2]


def test_uc002_transcribe_caller_speech_to_text() -> None:
    """
    Integration test for UC-002 third scenario.
    
    Scenario: Transcribe caller speech to text
      Given the caller speaks "Hello, can you help me?"
      When sufficient audio has been received
      Then the system transcribes the audio to text
      And an Utterance entity is created with the transcribed text
      And the Utterance has a confidence score
      And the Utterance is marked as "final"
    """
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance
    
    # Given the caller speaks "Hello, can you help me?"
    stream_id = StreamIdentifier("stream-456")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    conversation.activate()
    
    # When sufficient audio has been received (simulated)
    # Then the system transcribes the audio to text
    transcribed_text = "Hello, can you help me?"
    
    # And an Utterance entity is created with the transcribed text
    utterance = Utterance(
        text=transcribed_text,
        confidence=0.95,
        is_final=True,
        timestamp=datetime.now(timezone.utc)
    )
    
    conversation.add_utterance(utterance)
    
    assert utterance.text == "Hello, can you help me?"
    
    # And the Utterance has a confidence score
    assert utterance.confidence == 0.95
    assert 0.0 <= utterance.confidence <= 1.0
    
    # And the Utterance is marked as "final"
    assert utterance.is_final is True
    assert len(conversation.utterances) == 1


def test_uc002_handle_streaming_speech_with_partial_results() -> None:
    """
    Integration test for UC-002 fourth scenario.
    
    Scenario: Handle streaming speech with partial results
      Given the caller is speaking continuously
      When the caller says "What is..."
      Then a partial Utterance is created with text "What is"
      And the Utterance is marked as "partial"
      When the caller continues "the weather today?"
      Then the Utterance is updated to "What is the weather today?"
      And the Utterance is marked as "final"
    """
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance
    
    # Given the caller is speaking continuously
    stream_id = StreamIdentifier("stream-789")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    conversation.activate()
    
    # When the caller says "What is..."
    partial_utterance = Utterance(
        text="What is",
        confidence=0.80,
        is_final=False,
        timestamp=datetime.now(timezone.utc)
    )
    
    conversation.add_utterance(partial_utterance)
    
    # Then a partial Utterance is created with text "What is"
    assert partial_utterance.text == "What is"
    
    # And the Utterance is marked as "partial"
    assert partial_utterance.is_partial is True
    assert partial_utterance.is_final is False
    
    # When the caller continues "the weather today?"
    partial_utterance.update_text("What is the weather", confidence=0.85)
    assert partial_utterance.text == "What is the weather"
    
    # Then the Utterance is updated to "What is the weather today?"
    partial_utterance.finalize("What is the weather today?", confidence=0.93)
    
    assert partial_utterance.text == "What is the weather today?"
    
    # And the Utterance is marked as "final"
    assert partial_utterance.is_final is True
    assert partial_utterance.is_partial is False


def test_uc002_process_speech_with_pauses() -> None:
    """
    Integration test for UC-002 fifth scenario.
    
    Scenario: Process speech with pauses
      Given the caller speaks "Hello"
      And there is a 2-second pause
      When the caller speaks "How are you?"
      Then two separate Utterance entities are created
      And each Utterance represents a distinct speech segment
      And each has its own timestamp
    """
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance
    from time import sleep
    
    # Given the caller speaks "Hello"
    stream_id = StreamIdentifier("stream-pause")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    conversation.activate()
    
    # First utterance
    timestamp1 = datetime.now(timezone.utc)
    utterance1 = Utterance(
        text="Hello",
        confidence=0.96,
        is_final=True,
        timestamp=timestamp1
    )
    conversation.add_utterance(utterance1)
    
    # And there is a 2-second pause (simulated with small delay)
    sleep(0.01)  # Small delay to ensure different timestamp
    
    # When the caller speaks "How are you?"
    timestamp2 = datetime.now(timezone.utc)
    utterance2 = Utterance(
        text="How are you?",
        confidence=0.94,
        is_final=True,
        timestamp=timestamp2
    )
    conversation.add_utterance(utterance2)
    
    # Then two separate Utterance entities are created
    assert len(conversation.utterances) == 2
    
    # And each Utterance represents a distinct speech segment
    assert conversation.utterances[0].text == "Hello"
    assert conversation.utterances[1].text == "How are you?"
    
    # And each has its own timestamp
    assert conversation.utterances[0].timestamp == timestamp1
    assert conversation.utterances[1].timestamp == timestamp2
    assert timestamp2 > timestamp1  # Second utterance is later


def test_uc002_detect_and_handle_out_of_order_audio_chunks() -> None:
    """
    Integration test for UC-002 eighth scenario.
    
    Scenario: Detect and handle out-of-order audio chunks
      Given audio chunks are being received
      When chunk 3 arrives before chunk 2
      Then the system buffers the out-of-order chunk
      When chunk 2 arrives
      Then the system processes chunks in correct sequence order
      And transcription uses properly ordered audio
    """
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.audio_chunk import AudioChunk
    
    # Given audio chunks are being received
    stream_id = StreamIdentifier("stream-ooo")
    audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    
    conversation = ConversationSession.create(
        stream_identifier=stream_id,
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=audio_format
    )
    conversation.activate()
    
    # Add chunk 1 first (in order)
    chunk1 = AudioChunk(
        sequence_number=1,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=bytes(1600)
    )
    conversation.add_audio_chunk(chunk1)
    
    # When chunk 3 arrives before chunk 2
    chunk3 = AudioChunk(
        sequence_number=3,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=bytes(1600)
    )
    conversation.add_audio_chunk(chunk3)
    
    # Then the system buffers the out-of-order chunk
    assert len(conversation.audio_chunks) == 1  # Only chunk 1
    assert len(conversation.buffered_chunks) == 1  # Chunk 3 buffered
    
    # When chunk 2 arrives
    chunk2 = AudioChunk(
        sequence_number=2,
        timestamp=datetime.now(timezone.utc),
        audio_format=audio_format,
        audio_data=bytes(1600)
    )
    conversation.add_audio_chunk(chunk2)
    
    # Then the system processes chunks in correct sequence order
    assert len(conversation.audio_chunks) == 3
    assert len(conversation.buffered_chunks) == 0
    
    # And transcription uses properly ordered audio
    assert conversation.audio_chunks[0].sequence_number == 1
    assert conversation.audio_chunks[1].sequence_number == 2
    assert conversation.audio_chunks[2].sequence_number == 3
