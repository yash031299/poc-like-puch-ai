Feature: Process Caller Audio
  As a voice AI system
  I want to process incoming audio from callers
  So that their speech can be transcribed and understood

  Background:
    Given an active call is in progress
    And the ConversationSession is in "active" state

  Scenario: Receive and process single audio chunk
    Given the caller is connected
    When an audio chunk arrives from the telephony provider
    Then the system creates an AudioChunk entity
    And the AudioChunk has a sequence number
    And the AudioChunk has a timestamp
    And the AudioChunk is added to the ConversationSession
    And the audio is queued for transcription

  Scenario: Process multiple audio chunks in sequence
    Given the caller is speaking
    When audio chunks arrive with sequence numbers 1, 2, 3
    Then the system processes chunks in order
    And each chunk is timestamped correctly
    And chunks are accumulated for transcription

  Scenario: Transcribe caller speech to text
    Given the caller speaks "Hello, can you help me?"
    When sufficient audio has been received
    Then the system transcribes the audio to text
    And an Utterance entity is created with the transcribed text
    And the Utterance has a confidence score
    And the Utterance is marked as "final"
    And a CallerSpeechDetected event is published

  Scenario: Handle streaming speech with partial results
    Given the caller is speaking continuously
    When the caller says "What is..."
    Then a partial Utterance is created with text "What is"
    And the Utterance is marked as "partial"
    When the caller continues "the weather today?"
    Then the Utterance is updated to "What is the weather today?"
    And the Utterance is marked as "final"
    And a CallerSpeechDetected event is published

  Scenario: Process speech with pauses
    Given the caller speaks "Hello"
    And there is a 2-second pause
    When the caller speaks "How are you?"
    Then two separate Utterance entities are created
    And each Utterance represents a distinct speech segment
    And each has its own timestamp

  Scenario: Handle low confidence transcription
    Given the caller speaks with background noise
    When the transcription confidence is below 0.6
    Then the Utterance is still created
    And the low confidence score is recorded
    And the system may request clarification from the caller

  Scenario: Handle empty or silence audio
    Given the caller is not speaking
    When only silence is detected in audio chunks
    Then no Utterance is created
    And no CallerSpeechDetected event is published
    And the system continues listening

  Scenario: Detect and handle out-of-order audio chunks
    Given audio chunks are being received
    When chunk 3 arrives before chunk 2
    Then the system buffers the out-of-order chunk
    When chunk 2 arrives
    Then the system processes chunks in correct sequence order
    And transcription uses properly ordered audio

  Scenario: Handle interrupted speech (caller cut off)
    Given the caller is speaking
    When the call is unexpectedly terminated mid-speech
    Then the system processes accumulated audio
    And a final Utterance is created with available speech
    And the Utterance is marked as potentially incomplete

  Scenario: Process audio in different formats
    Given a call with 8kHz sample rate audio
    When audio chunks arrive
    Then the system processes the audio according to its AudioFormat
    And transcription adapts to the sample rate

  Scenario: Handle rapid-fire speech (fast talker)
    Given the caller speaks very quickly
    When continuous audio arrives without pauses
    Then the system segments speech appropriately
    And multiple Utterances may be created from continuous audio
    And each Utterance represents a logical speech unit

  # Edge Cases

  Scenario: Handle audio chunk with invalid format
    Given a call is using PCM16LE audio format
    When an audio chunk arrives with incompatible encoding
    Then the system detects the format mismatch
    And the chunk is rejected
    And an error is logged
    And the call continues with subsequent valid chunks

  Scenario: Handle extremely large audio chunk
    Given the maximum audio chunk size is 100KB
    When an audio chunk larger than 100KB arrives
    Then the system splits the chunk into smaller segments
    And each segment is processed independently
    And sequence numbers are maintained

  Scenario: Process audio during AI response playback
    Given the AI is currently speaking to the caller
    When the caller interrupts by speaking
    Then the system continues to process caller audio
    And the interruption is detected
    And the AI response may be interrupted

  # Business Rules

  Rule: Audio chunks must be processed in sequence order
    Scenario: Enforce sequential processing
      Given audio chunks 1, 3, 2 arrive
      Then the system buffers chunk 3
      And processes chunks in order 1, 2, 3
      And transcription is accurate due to correct ordering

  Rule: Utterances must have associated audio chunks
    Scenario: No utterance without audio
      When no audio chunks have been received
      Then no Utterance entities exist
      And no CallerSpeechDetected events are published

  Rule: Speech detection respects language and accent
    Scenario: Transcribe non-English speech
      Given the call custom parameters specify language "es-ES"
      When the caller speaks in Spanish
      Then the transcription uses Spanish language model
      And the Utterance contains Spanish text

  Rule: Audio processing must handle real-time constraints
    Scenario: Maintain low latency processing
      Given audio chunks arrive every 100ms
      When each chunk is processed
      Then processing completes within 50ms
      And no audio backlog accumulates
      And the system maintains real-time performance
