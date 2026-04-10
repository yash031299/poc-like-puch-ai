"""ConversationSession aggregate - root aggregate for managing call lifecycle."""

from typing import Dict, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

from src.domain.entities.call_session import CallSession
from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance
from src.domain.entities.ai_response import AIResponse
from src.domain.entities.speech_segment import SpeechSegment
from src.domain.value_objects.stream_identifier import StreamIdentifier
from src.domain.value_objects.audio_format import AudioFormat


@dataclass
class InterruptEvent:
    """Record of a user interrupt during response delivery."""
    timestamp: datetime
    token_count: int
    context: str
    intent: str  # User's inferred intent (e.g., "clarification", "objection", "restart")


class ConversationSession:
    """
    Aggregate root managing the complete lifecycle of a phone conversation.
    
    Business Rule: ConversationSession is the transaction boundary and
    single point of access for all entities related to a call. External
    systems can only interact with the conversation through this aggregate root.
    """
    
    def __init__(self, call_session: CallSession) -> None:
        """
        Create a ConversationSession with an existing CallSession.
        
        Args:
            call_session: The CallSession entity (aggregate root)
        """
        self._call_session = call_session
        self._audio_chunks: List[AudioChunk] = []
        self._buffered_chunks: Dict[int, AudioChunk] = {}  # sequence -> chunk
        self._utterances: List[Utterance] = []
        self._ai_responses: List[AIResponse] = []
        self._speech_segments: List[SpeechSegment] = []
        self._interaction_state: str = "listening"
        self._interrupted: bool = False  # User interruption flag
        self._interrupt_timestamp: Optional[object] = None  # When interrupt occurred
        
        # Phase 3D.2: Adaptive Noise Floor Learning
        self._noise_floor_db: float = -40.0  # Default noise floor
        self._is_noise_floor_learned: bool = False  # Flag: learned vs default
        self._interrupt_history: List[InterruptEvent] = []  # History of all interrupts
    
    @classmethod
    def create(
        cls,
        stream_identifier: StreamIdentifier,
        caller_number: str,
        called_number: str,
        audio_format: AudioFormat,
        custom_parameters: Optional[Dict[str, str]] = None
    ) -> "ConversationSession":
        """
        Factory method to create a new ConversationSession.
        
        Args:
            stream_identifier: Unique identifier for this call stream
            caller_number: Phone number of the caller
            called_number: Phone number that was dialed
            audio_format: Audio format specification
            custom_parameters: Optional custom routing parameters
            
        Returns:
            New ConversationSession instance
        """
        call_session = CallSession(
            stream_identifier=stream_identifier,
            caller_number=caller_number,
            called_number=called_number,
            audio_format=audio_format,
            custom_parameters=custom_parameters
        )
        return cls(call_session)
    
    @property
    def call_session(self) -> CallSession:
        """Get the underlying CallSession (aggregate root entity)."""
        return self._call_session
    
    @property
    def stream_identifier(self) -> StreamIdentifier:
        """Get the unique stream identifier for this conversation."""
        return self._call_session.stream_identifier

    @property
    def stream_id(self) -> str:
        """Convenience property: stream identifier as plain string."""
        return str(self._call_session.stream_identifier)

    @property
    def caller_number(self) -> str:
        """Phone number of the caller."""
        return self._call_session.caller_number

    @property
    def called_number(self) -> str:
        """Phone number that was dialed (AI agent's number)."""
        return self._call_session.called_number

    @property
    def is_active(self) -> bool:
        """True when the session is in the active state."""
        return self._call_session.state == "active"

    @property
    def is_ended(self) -> bool:
        """Check if the conversation has ended."""
        return self._call_session.state == "ended"

    @property
    def interaction_state(self) -> str:
        """Current conversational interaction state: listening/thinking/speaking."""
        return self._interaction_state
    
    @property
    def audio_chunks(self) -> List[AudioChunk]:
        """Get the ordered list of audio chunks received."""
        return list(self._audio_chunks)  # Return copy for immutability
    
    @property
    def buffered_chunks(self) -> List[AudioChunk]:
        """Get list of buffered out-of-order chunks."""
        return list(self._buffered_chunks.values())
    
    @property
    def utterances(self) -> List[Utterance]:
        """Get the list of utterances (transcribed speech)."""
        return list(self._utterances)  # Return copy for immutability
    
    @property
    def latest_utterance(self) -> Optional[Utterance]:
        """Get the most recent utterance, or None if no utterances exist."""
        return self._utterances[-1] if self._utterances else None
    
    @property
    def final_utterances(self) -> List[Utterance]:
        """Get only the final (completed) utterances."""
        return [u for u in self._utterances if u.is_final]
    
    def activate(self) -> None:
        """
        Activate the conversation (first audio received).
        
        Business Rule: Transitions the call from initiated to active state.
        """
        self._call_session.activate()
        self._interaction_state = "listening"
    
    def end(self) -> None:
        """
        End the conversation.
        
        Business Rule: Transitions the call to ended state and prevents
        further modifications.
        """
        self._call_session.end()
        self._interaction_state = "listening"

    def set_listening(self) -> None:
        """Mark conversation as listening for caller input."""
        if self.is_ended:
            raise ValueError("Cannot update interaction state of an ended conversation")
        self._interaction_state = "listening"

    def set_thinking(self) -> None:
        """Mark conversation as thinking while STT/LLM pipeline is running."""
        if self.is_ended:
            raise ValueError("Cannot update interaction state of an ended conversation")
        self._interaction_state = "thinking"

    def set_speaking(self) -> None:
        """Mark conversation as speaking while TTS is being streamed."""
        if self.is_ended:
            raise ValueError("Cannot update interaction state of an ended conversation")
        self._interaction_state = "speaking"
    
    def mark_interrupted(self) -> None:
        """
        Mark session as interrupted by user.
        
        Business Rule: Called when user audio is detected during SPEAKING state.
        Sets the interrupt flag and returns to listening state.
        """
        if not self.is_ended:
            self._interrupted = True
            self._interrupt_timestamp = datetime.now(timezone.utc)
            self.set_listening()
    
    def is_interrupted(self) -> bool:
        """
        Check if session has been interrupted.
        
        Returns:
            True if user has interrupted the AI response
        """
        return self._interrupted
    
    def reset_interrupt(self) -> None:
        """
        Reset interrupt flag for the next response.
        
        Called after handling an interrupt to prepare for next cycle.
        """
        self._interrupted = False
        self._interrupt_timestamp = None
    
    @property
    def interrupt_history(self) -> List[InterruptEvent]:
        """Get the history of all interrupts in this session."""
        return list(self._interrupt_history)  # Return copy for immutability
    
    def record_interrupt(
        self,
        token_count: int,
        context: str,
        intent: str
    ) -> None:
        """
        Record an interrupt event in the session history.
        
        Business Rule: Max 100 interrupts per session to prevent memory bloat.
        
        Args:
            token_count: Which token # the user interrupted at
            context: What was being said when interrupted
            intent: User's inferred intent (e.g., "clarification", "objection")
            
        Raises:
            ValueError: If call has ended or too many interrupts recorded
        """
        if self.is_ended:
            raise ValueError("Cannot record interrupt on an ended conversation")
        if token_count < 0:
            raise ValueError("token_count cannot be negative")
        if not context:
            raise ValueError("context cannot be empty")
        if not intent:
            raise ValueError("intent cannot be empty")
        if len(self._interrupt_history) >= 100:
            raise ValueError("Maximum interrupts per session (100) reached")
        
        event = InterruptEvent(
            timestamp=datetime.now(timezone.utc),
            token_count=token_count,
            context=context,
            intent=intent
        )
        self._interrupt_history.append(event)
    
    def add_audio_chunk(self, chunk: AudioChunk) -> None:
        """
        Add an audio chunk to the conversation.
        
        Business Rule: Chunks must be processed in sequence order.
        Out-of-order chunks are buffered until gaps are filled.
        
        Args:
            chunk: The audio chunk to add
            
        Raises:
            ValueError: If chunk format mismatches, is duplicate, or call has ended
        """
        if self.is_ended:
            raise ValueError("Cannot add audio to an ended conversation")

        # Validate audio format matches call format
        if chunk.audio_format != self._call_session.audio_format:
            raise ValueError("Audio format mismatch")
        
        # Check for duplicate
        if any(c.sequence_number == chunk.sequence_number for c in self._audio_chunks):
            raise ValueError(f"Audio chunk with sequence {chunk.sequence_number} already exists")
        
        if chunk.sequence_number in self._buffered_chunks:
            raise ValueError(f"Audio chunk with sequence {chunk.sequence_number} already exists")
        
        # Determine expected next sequence number
        expected_seq = len(self._audio_chunks) + 1
        
        if chunk.sequence_number == expected_seq:
            # In order - add to main list
            self._audio_chunks.append(chunk)
            
            # Process any buffered chunks that are now in sequence
            self._flush_buffered_chunks()
        elif chunk.sequence_number > expected_seq:
            # Out of order - buffer it
            self._buffered_chunks[chunk.sequence_number] = chunk
        else:
            # Chunk is from the past (already processed) - reject
            raise ValueError(f"Audio chunk with sequence {chunk.sequence_number} already processed")
    
    def _flush_buffered_chunks(self) -> None:
        """
        Add any buffered chunks that are now in sequence.
        
        Business Rule: Process buffered chunks in order when gaps are filled.
        """
        expected_seq = len(self._audio_chunks) + 1
        
        while expected_seq in self._buffered_chunks:
            chunk = self._buffered_chunks.pop(expected_seq)
            self._audio_chunks.append(chunk)
            expected_seq += 1
    
    def get_audio_chunk(self, sequence_number: int) -> Optional[AudioChunk]:
        """
        Retrieve an audio chunk by sequence number.
        
        Args:
            sequence_number: The sequence number to retrieve
            
        Returns:
            The audio chunk, or None if not found
        """
        for chunk in self._audio_chunks:
            if chunk.sequence_number == sequence_number:
                return chunk
        return None
    
    def add_utterance(self, utterance: Utterance) -> None:
        """
        Add an utterance (transcribed speech) to the conversation.

        Business Rule: Utterances represent transcribed caller speech.
        They can be partial (in-progress) or final (completed).
        """
        self._utterances.append(utterance)

    def reset_context(self) -> None:
        """
        Clear conversational context mid-call.

        Business Rule: Triggered when Exotel sends a 'clear' event (caller
        says 'start over'). Utterances and AI responses are wiped so the
        next exchange starts fresh. Audio chunks are preserved as part of
        the raw call record. Session state and caller info are unchanged.
        Interrupt history is NOT cleared (preserved for analytics).

        Raises:
            ValueError: If the session has already ended.
        """
        if self.is_ended:
            raise ValueError("Cannot reset context of an ended conversation")
        self._utterances.clear()
        self._ai_responses.clear()
        self._speech_segments.clear()
        self._buffered_chunks.clear()

    # ── AIResponse ────────────────────────────────────────────────────────────

    @property
    def ai_responses(self) -> List[AIResponse]:
        """Get all AI responses for this conversation."""
        return list(self._ai_responses)

    @property
    def latest_ai_response(self) -> Optional[AIResponse]:
        """Get the most recently added AI response, or None."""
        return self._ai_responses[-1] if self._ai_responses else None

    def add_ai_response(self, response: AIResponse) -> None:
        """Add an AI-generated response to the conversation."""
        self._ai_responses.append(response)

    def get_ai_responses_for(self, utterance_id: str) -> List[AIResponse]:
        """Get all AI responses linked to a specific utterance."""
        return [r for r in self._ai_responses if r.utterance_id == utterance_id]

    # ── SpeechSegment ─────────────────────────────────────────────────────────

    @property
    def speech_segments(self) -> List[SpeechSegment]:
        """Get all synthesized speech segments for this conversation."""
        return list(self._speech_segments)

    def add_speech_segment(self, segment: SpeechSegment) -> None:
        """Add a synthesized speech segment to the conversation."""
        self._speech_segments.append(segment)

    def get_speech_segments_for(self, response_id: str) -> List[SpeechSegment]:
        """Get all speech segments linked to a specific AI response, ordered by position."""
        return sorted(
            [s for s in self._speech_segments if s.response_id == response_id]
        )

    # ── Noise Floor Learning (Phase 3D.2) ──────────────────────────────────

    def set_noise_floor(self, db: float) -> None:
        """
        Set the learned noise floor threshold.

        Business Rule: Called after NoiseFloorLearner completes learning.
        Marks the threshold as learned (vs default) and stores it for
        use by InterruptDetector during subsequent interaction cycles.

        Args:
            db: Learned noise floor in dB (must be <= 0)

        Raises:
            ValueError: If db > 0 or session has ended
        """
        if self.is_ended:
            raise ValueError("Cannot set noise floor on an ended conversation")
        
        if db > 0:
            raise ValueError(f"Noise floor must be <= 0dB, got {db}")
        
        self._noise_floor_db = db
        self._is_noise_floor_learned = True

    def get_noise_floor(self) -> float:
        """
        Get the noise floor threshold (learned or default).

        Returns:
            Noise floor in dB (always <= 0)
        """
        return self._noise_floor_db

    def is_noise_floor_learned(self) -> bool:
        """
        Check if noise floor has been learned.

        Returns:
            True if learned from first utterance, False if using default
        """
        return self._is_noise_floor_learned

    def __eq__(self, other: object) -> bool:
        """Check equality based on stream_identifier (aggregate identity)."""
        if not isinstance(other, ConversationSession):
            return False
        return self.stream_identifier == other.stream_identifier
    
    def __hash__(self) -> int:
        """Make ConversationSession hashable based on identity."""
        return hash(self.stream_identifier)
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"ConversationSession(stream_id={self.stream_identifier}, "
            f"state='{self.call_session.state}')"
        )
