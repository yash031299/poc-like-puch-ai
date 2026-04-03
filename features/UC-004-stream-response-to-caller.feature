Feature: Stream Response to Caller
  As a voice AI system
  I want to convert AI responses to speech and stream to caller
  So that the caller can hear the AI's reply

  Background:
    Given an active call is in progress
    And an AIResponse has been generated

  Scenario: Synthesize AI response to speech
    Given the AIResponse contains text "The weather is sunny today"
    When the text-to-speech process begins
    Then a SpeechSegment entity is created
    And the SpeechSegment contains synthesized audio
    And the audio format matches the call's AudioFormat
    And the SpeechSegment is associated with the AIResponse

  Scenario: Stream speech audio to caller
    Given a SpeechSegment is ready
    When the audio is transmitted to the telephony provider
    Then audio chunks are sent in sequence
    And each chunk has proper sequence numbering
    And each chunk has accurate timestamps
    And an AudioReadyForPlayback event is published for each chunk

  Scenario: Stream long response incrementally
    Given the AIResponse is "Here's a long explanation..." (1000 words)
    When text-to-speech synthesis begins
    Then audio is generated in small segments
    And each SpeechSegment is streamed immediately
    And the caller hears audio without waiting for complete synthesis
    And perceived latency is minimized

  Scenario: Stream response as AI generates it (full streaming pipeline)
    Given the AI is generating a streaming response
    When each partial AIResponse chunk is generated
    Then that chunk is immediately synthesized to speech
    And the audio is immediately streamed to caller
    And the caller hears the response with minimal delay
    And the end-to-end pipeline maintains low latency

  Scenario: Handle audio playback with proper pacing
    Given a SpeechSegment is being played to caller
    When the audio is transmitted
    Then the playback rate matches natural speech tempo
    And there are no awkward pauses between segments
    And the audio flows smoothly

  Scenario: Convert speech at appropriate volume
    Given a SpeechSegment is synthesized
    When the audio is generated
    Then the volume level is normalized
    And the audio is comfortable for caller to hear
    And volume is consistent across segments

  Scenario: Handle chunking for telephony provider constraints
    Given the telephony provider requires chunks in 320-byte multiples
    When SpeechSegment audio is prepared
    Then the audio is chunked appropriately
    And each chunk size is a multiple of 320 bytes
    And no audio data is lost in chunking

  Scenario: Maintain sequence numbers across streaming
    Given multiple SpeechSegments are being streamed
    When audio chunks are sent to telephony provider
    Then sequence numbers increment correctly
    And no sequence numbers are skipped
    And the provider can reconstruct audio in order

  # Edge Cases

  Scenario: Handle audio synthesis failure
    Given an AIResponse is ready for synthesis
    When the text-to-speech service fails
    Then the system retries synthesis
    If all retries fail
    Then the system logs the error
    And the call continues without that response
    And the caller receives a fallback notification

  Scenario: Handle caller interruption during playback
    Given the AI is speaking to the caller
    When the caller starts speaking
    Then the system detects the interruption
    And the current audio playback can be interrupted
    And the system processes the new caller audio
    And the interrupted AIResponse is marked as cancelled

  Scenario: Clear buffered audio on interruption
    Given audio is buffered for playback
    When the caller interrupts
    Then the system sends a "clear" command to telephony provider
    And buffered audio is discarded
    And new audio can begin immediately

  Scenario: Handle slow text-to-speech synthesis
    Given a long AIResponse needs synthesis
    When synthesis is taking longer than expected
    Then the system monitors synthesis progress
    And already-synthesized audio continues streaming
    And the system doesn't block on complete synthesis

  Scenario: Handle audio encoding errors
    Given synthesized audio needs encoding
    When encoding to the required format fails
    Then the system attempts alternative encoding
    And logs the encoding error
    And retries with fallback parameters

  Scenario: Stream with network congestion
    Given audio is being streamed to caller
    When network latency increases
    Then the system buffers audio appropriately
    And maintains playback continuity
    And doesn't cause audio stuttering

  Scenario: Handle zero-length or silent speech segments
    Given an AIResponse contains only punctuation "..."
    When synthesis generates silent audio
    Then the system detects the silence
    And the segment is skipped or replaced with brief pause
    And no empty audio chunks are sent

  # Business Rules

  Rule: Audio format must match call AudioFormat
    Scenario: Consistent audio format
      Given a call uses 16kHz PCM16LE mono audio
      When SpeechSegments are synthesized
      Then all audio is 16kHz PCM16LE mono
      And no format conversion is needed by telephony provider

  Rule: Sequence numbers must be monotonically increasing
    Scenario: Strict sequence ordering
      Given audio chunks are being transmitted
      Then sequence number N is followed by N+1
      And no sequence numbers are reused
      And gaps indicate lost packets

  Rule: Audio playback must respect timing constraints
    Scenario: Real-time audio streaming
      Given audio is synthesized at rate R
      Then audio is transmitted at rate ≥ R
      And no backlog accumulates
      And the caller hears audio in real-time

  Rule: SpeechSegment must be associated with AIResponse
    Scenario: Traceable audio sources
      When a SpeechSegment is created
      Then it must reference a specific AIResponse
      And the AIResponse must exist in the ConversationSession
      And audio can be traced back to the AI's text

  Rule: Audio chunks must be properly sized for provider
    Scenario: Chunk size compliance
      Given the telephony provider requires 320-byte multiples
      When audio chunks are prepared
      Then each chunk size is N * 320 bytes
      And chunk sizes are between 3.2KB and 100KB
      And the provider can process chunks without errors

  Rule: Interruptions must be handled gracefully
    Scenario: Smooth interruption handling
      Given the AI is speaking
      When the caller interrupts
      Then current playback stops within 200ms
      And the caller's speech is processed immediately
      And no audio artifacts or glitches occur
      And the conversation flow feels natural

  Rule: Audio quality must meet minimum standards
    Scenario: Quality assurance
      When speech is synthesized
      Then audio has no clipping or distortion
      And volume is within acceptable range
      And speech is clearly intelligible
      And quality is consistent across segments
