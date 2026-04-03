# Domain Definitions - Voice AI Pipeline

**Last Updated:** 2026-04-03  
**Format:** Business language (Gherkin/Given-When-Then style)  
**Purpose:** Define core business concepts without implementation details

---

## Business Domain: Telephone-Based AI Conversations

### Domain: Voice Call Management

A **Voice Call** is a bidirectional audio communication channel between a **Caller** and an **AI Agent**.

**Business Rules:**
- Each call has a unique identifier
- A call begins when the caller connects
- A call ends when either party disconnects
- Multiple calls can be active simultaneously
- Each call is independent of other calls

---

## Core Entities (Business Concepts)

### Entity: CallSession

**Business Definition:**  
A CallSession represents an active telephone conversation between a human caller and an AI agent.

**Business Rules:**
- Given a caller initiates a phone call
- When the telephony system connects the call
- Then a CallSession is created with a unique identifier
- And the CallSession tracks the call's start time
- And the CallSession maintains the caller's phone number
- And the CallSession knows the dialed phone number

**Invariants:**
- A CallSession must always have a unique identifier
- A CallSession start time cannot be in the future
- A CallSession cannot end before it starts

**Lifecycle States:**
- `initiated` - Call connected, waiting for first audio
- `active` - Actively exchanging audio
- `ended` - Call has terminated

---

### Entity: AudioChunk

**Business Definition:**  
An AudioChunk is a discrete segment of audio data from either the caller or the AI agent.

**Business Rules:**
- Given audio is flowing through the system
- When audio data arrives or is generated
- Then it is divided into AudioChunks
- And each AudioChunk has a sequence number for ordering
- And each AudioChunk has a timestamp
- And each AudioChunk contains raw audio samples

**Invariants:**
- AudioChunks must be ordered by sequence number
- AudioChunks cannot have negative timestamps
- AudioChunks must contain valid audio data

**Properties:**
- Sequence number (for ordering)
- Timestamp (when recorded/generated)
- Audio format (sample rate, encoding, channels)
- Raw audio samples (bytes)

---

### Entity: Utterance

**Business Definition:**  
An Utterance is a transcribed segment of speech from the caller.

**Business Rules:**
- Given the caller is speaking
- When the speech is converted to text
- Then an Utterance is created containing the transcribed text
- And the Utterance includes a confidence score
- And the Utterance knows whether speech is still in progress

**Invariants:**
- Utterance text cannot be empty
- Confidence score must be between 0 and 1
- Final utterances cannot be modified

**States:**
- `partial` - Speech still in progress (may change)
- `final` - Speech segment complete (immutable)

---

### Entity: AIResponse

**Business Definition:**  
An AIResponse is the AI agent's generated reply to the caller's utterance.

**Business Rules:**
- Given the AI receives an Utterance
- When the AI generates a response
- Then an AIResponse is created containing the reply text
- And the AIResponse can be delivered incrementally (streaming)
- And the AIResponse knows which Utterance it's responding to

**Invariants:**
- AIResponse must be associated with an Utterance
- AIResponse text cannot be empty once complete
- Streaming responses build progressively (monotonic)

**States:**
- `generating` - AI is still producing the response
- `complete` - Response fully generated
- `delivered` - Response sent to caller as speech

---

### Entity: SpeechSegment

**Business Definition:**  
A SpeechSegment is synthesized audio from AI-generated text.

**Business Rules:**
- Given an AIResponse contains text
- When the text is converted to speech
- Then a SpeechSegment is created containing audio data
- And the SpeechSegment can be streamed incrementally
- And the SpeechSegment knows which AIResponse it represents

**Invariants:**
- SpeechSegment must be associated with an AIResponse
- SpeechSegment audio format must match CallSession audio format
- SpeechSegment cannot be empty once complete

---

## Value Objects (Immutable Concepts)

### Value Object: StreamIdentifier

**Business Definition:**  
A StreamIdentifier is a unique, immutable identifier for a call stream.

**Business Rules:**
- Given a new call stream is created
- When a StreamIdentifier is assigned
- Then it uniquely identifies that stream for its entire lifecycle
- And the identifier cannot be changed
- And the identifier can be used to correlate events

**Properties:**
- Unique string value (e.g., UUID or provider-assigned ID)

**Invariants:**
- Must be unique across all active and historical streams
- Cannot be null or empty
- Immutable once assigned

---

### Value Object: AudioFormat

**Business Definition:**  
AudioFormat describes the technical characteristics of audio data.

**Business Rules:**
- Given audio is being processed
- When the system needs to encode or decode audio
- Then AudioFormat specifies how to interpret the audio samples
- And AudioFormat includes sample rate (samples per second)
- And AudioFormat includes encoding (e.g., PCM16LE)
- And AudioFormat includes number of channels (mono/stereo)

**Properties:**
- `sample_rate` - Samples per second (e.g., 8000, 16000, 24000 Hz)
- `encoding` - Format (e.g., "PCM16LE" = 16-bit PCM little-endian)
- `channels` - Number of audio channels (1=mono, 2=stereo)
- `bit_depth` - Bits per sample (e.g., 16)

**Invariants:**
- Sample rate must be positive
- Channels must be 1 or 2 (mono or stereo)
- Encoding must be supported (PCM16LE for MVP)
- Immutable once created

---

### Value Object: Timestamp

**Business Definition:**  
A Timestamp is a point in time relative to the start of a call.

**Business Rules:**
- Given events occur during a call
- When an event needs to be timestamped
- Then a Timestamp represents milliseconds since call start
- And Timestamps are monotonically increasing within a call

**Properties:**
- `milliseconds_since_start` - Integer milliseconds

**Invariants:**
- Cannot be negative
- Monotonically increasing within same CallSession
- Immutable once created

---

## Aggregates (Business Transaction Boundaries)

### Aggregate: ConversationSession

**Business Definition:**  
A ConversationSession is the root aggregate that manages the entire lifecycle of a phone call interaction.

**Aggregate Root:** CallSession

**Contains:**
- One CallSession (root entity)
- Multiple AudioChunks (incoming from caller)
- Multiple Utterances (transcribed caller speech)
- Multiple AIResponses (AI-generated replies)
- Multiple SpeechSegments (synthesized speech to caller)

**Business Rules:**
- Given a caller initiates a phone call
- When the ConversationSession is created
- Then it manages all entities related to that call
- And all entities within the aggregate share the same lifecycle
- And the aggregate ensures consistency across all entities
- And external systems can only access entities through the aggregate root

**Invariants:**
- All contained entities must reference the same CallSession
- Audio chunks must be in sequence order
- Each Utterance must have been created from AudioChunks
- Each AIResponse must be responding to an Utterance
- Each SpeechSegment must be synthesized from an AIResponse
- When CallSession ends, no new entities can be added

**Transactions:**
- Creating a new conversation (atomic)
- Processing incoming audio (atomic)
- Generating and delivering response (atomic)
- Ending the conversation (atomic)

---

## Domain Events (Things That Happen)

### Event: CallInitiated

**Business Meaning:**  
A new phone call has been successfully connected to the system.

**Scenario:**
```gherkin
Given a caller dials the phone number
When the telephony system connects the call
Then a CallInitiated event is published
And the event contains the unique stream identifier
And the event contains the caller's phone number
And the event contains the dialed phone number
And the event contains the call start timestamp
```

**Event Payload:**
- `stream_identifier` - Unique ID for this call
- `caller_number` - Caller's phone number
- `called_number` - Number that was dialed
- `started_at` - Timestamp when call connected

---

### Event: CallerSpeechDetected

**Business Meaning:**  
The caller has spoken, and speech has been transcribed to text.

**Scenario:**
```gherkin
Given an active call is in progress
When the caller speaks
And the speech is transcribed to text
Then a CallerSpeechDetected event is published
And the event contains the transcribed text
And the event indicates if speech is still continuing
And the event contains a confidence score
```

**Event Payload:**
- `stream_identifier` - Which call this is from
- `utterance_text` - Transcribed text
- `is_final` - Whether speech is complete
- `confidence` - Transcription confidence (0.0 to 1.0)
- `detected_at` - When speech was detected

---

### Event: AIResponseGenerated

**Business Meaning:**  
The AI has generated a response to the caller's speech.

**Scenario:**
```gherkin
Given the AI has received caller speech
When the AI generates a response
Then an AIResponseGenerated event is published
And the event contains the response text
And the event indicates if more text is coming (streaming)
```

**Event Payload:**
- `stream_identifier` - Which call this is for
- `response_text` - AI-generated text
- `is_complete` - Whether response is fully generated
- `responding_to` - Reference to the Utterance being answered
- `generated_at` - When response was created

---

### Event: AudioReadyForPlayback

**Business Meaning:**  
Synthesized speech audio is ready to be played to the caller.

**Scenario:**
```gherkin
Given the AI has generated a text response
When the text is converted to speech
Then an AudioReadyForPlayback event is published
And the event contains audio data ready to transmit
And the event maintains proper sequencing
```

**Event Payload:**
- `stream_identifier` - Which call this is for
- `audio_chunk` - Synthesized audio data
- `sequence_number` - For ordering
- `synthesized_at` - When audio was created

---

### Event: CallEnded

**Business Meaning:**  
The phone call has been terminated by either the caller or the system.

**Scenario:**
```gherkin
Given an active call is in progress
When either party terminates the call
Then a CallEnded event is published
And the event contains the termination reason
And the event contains the call duration
And the event finalizes the call session
```

**Event Payload:**
- `stream_identifier` - Which call ended
- `reason` - Why call ended (caller_hung_up, system_error, timeout, etc.)
- `duration_ms` - How long the call lasted
- `ended_at` - When call terminated

---

## Business Workflows

### Workflow: Handle Incoming Call

**Business Goal:**  
Accept and initialize a new phone conversation.

**Scenario:**
```gherkin
Feature: Accept Incoming Phone Call

  As a telephone system
  I want to accept incoming calls from users
  So that they can interact with the AI agent

  Scenario: Successful call connection
    Given a caller dials the AI agent's phone number
    When the telephony system routes the call to our service
    Then the system creates a new ConversationSession
    And the system assigns a unique StreamIdentifier
    And the system publishes a CallInitiated event
    And the system is ready to receive audio from the caller

  Scenario: Call with custom parameters
    Given a caller dials the AI agent with custom routing parameters
    When the call is connected
    Then the system captures the custom parameters
    And the custom parameters are available to the ConversationSession
```

---

### Workflow: Process Caller Speech

**Business Goal:**  
Convert caller's voice to text so the AI can understand and respond.

**Scenario:**
```gherkin
Feature: Process Caller Speech

  As a voice AI system
  I want to transcribe caller speech to text
  So that the AI can understand what the caller is saying

  Scenario: Caller speaks a complete sentence
    Given an active call is in progress
    When the caller speaks "What is the weather today?"
    And the speech is complete
    Then the system transcribes the speech to text
    And the system publishes a CallerSpeechDetected event
    And the event indicates the speech is final
    And the transcription confidence is above threshold

  Scenario: Caller speaks with pauses (streaming transcription)
    Given an active call is in progress
    When the caller starts speaking "What is..."
    Then the system publishes a partial CallerSpeechDetected event
    When the caller continues "the weather today?"
    Then the system publishes a final CallerSpeechDetected event
    And the final transcription is "What is the weather today?"
```

---

### Workflow: Generate AI Response

**Business Goal:**  
Generate an intelligent response to the caller's speech.

**Scenario:**
```gherkin
Feature: Generate AI Response

  As an AI agent
  I want to generate appropriate responses to caller speech
  So that I can have meaningful conversations

  Scenario: Generate response to caller question
    Given the caller asked "What is the weather today?"
    When the AI processes the question
    Then the AI generates a relevant response
    And the response is contextually appropriate
    And the system publishes an AIResponseGenerated event

  Scenario: Stream long response incrementally
    Given the caller asked a complex question
    When the AI generates a long response
    Then the response is streamed in chunks
    And each chunk is published as soon as available
    And the final chunk is marked as complete
```

---

### Workflow: Deliver Speech to Caller

**Business Goal:**  
Convert AI's text response to speech and play it to the caller.

**Scenario:**
```gherkin
Feature: Stream Response to Caller

  As a voice AI system
  I want to convert AI responses to speech
  So that the caller can hear the AI's reply

  Scenario: Synthesize and play response
    Given the AI generated response "The weather is sunny today"
    When the text is converted to speech
    Then the system creates SpeechSegments
    And the audio is properly formatted for the telephony system
    And the system publishes AudioReadyForPlayback events
    And the audio is transmitted to the caller in sequence

  Scenario: Stream long response as it's generated
    Given the AI is generating a long streaming response
    When each text chunk becomes available
    Then the system immediately converts it to speech
    And the system streams the audio to the caller
    And the caller hears the response with minimal delay
```

---

### Workflow: End Call

**Business Goal:**  
Properly terminate the call and clean up resources.

**Scenario:**
```gherkin
Feature: Handle Call Termination

  As a voice AI system
  I want to properly handle call termination
  So that resources are cleaned up and events are recorded

  Scenario: Caller hangs up
    Given an active call is in progress
    When the caller terminates the call
    Then the system detects the termination
    And the system publishes a CallEnded event
    And the event indicates reason as "caller_hung_up"
    And the system releases all resources for that call

  Scenario: System terminates due to error
    Given an active call is in progress
    When an unrecoverable error occurs
    Then the system gracefully terminates the call
    And the system publishes a CallEnded event
    And the event indicates reason as "system_error"
    And the system logs the error details
```

---

## Ubiquitous Language (Team Vocabulary)

### Terms We Use

- **CallSession** - NOT "connection" or "socket" (business concept, not technical)
- **Caller** - The human making the phone call
- **AI Agent** - The AI system responding to the caller
- **Utterance** - Transcribed speech from caller (NOT "message" or "text")
- **AIResponse** - AI's generated reply (NOT "answer" or "output")
- **SpeechSegment** - Synthesized audio (NOT "audio chunk" - that's for input)
- **AudioChunk** - Raw audio data segment
- **StreamIdentifier** - Unique ID for a call (NOT "session ID" or "connection ID")
- **ConversationSession** - The entire call interaction (aggregate root)

### Terms We Avoid

- ❌ "WebSocket" - Infrastructure detail, not business concept
- ❌ "Exotel" - Provider detail, not domain concept
- ❌ "Gemini/OpenAI" - Implementation detail
- ❌ "Base64" - Encoding detail, not business concept
- ❌ "PCM16LE" - Technical format, not business concept (use AudioFormat)

**Why:** Domain layer must use business language, not technical jargon. Infrastructure adapters translate between business concepts and technical protocols.

---

## Business Constraints

### Performance Constraints

**Latency Requirement:**  
The perceived latency between caller speech and AI response must feel natural (target: <500ms excluding LLM processing).

**Rationale:** Humans expect conversational turn-taking similar to talking with another person. Long delays break the illusion and frustrate callers.

### Scale Constraints

**Concurrent Calls:**  
- PoC: Support 10 concurrent calls
- Production: Design for horizontal scaling to millions

**Rationale:** Single-server limitations require distributed architecture for production scale.

### Quality Constraints

**Transcription Accuracy:**  
Speech transcription must be >85% accurate for production use.

**Rationale:** Poor transcription causes AI misunderstanding and bad user experience.

### Reliability Constraints

**Call Drop Rate:**  
Call drop rate must be <0.1% (999 successful calls per 1000).

**Rationale:** Dropped calls damage user trust and business reputation.

---

## Notes for Developers

### Domain Layer Purity
- NO imports from `infrastructure/`, `adapters/`, or any external libraries
- Pure Python only (standard library is OK for data structures)
- Business logic only, no technical concerns

### Test First
- Write Gherkin scenario FIRST
- Write failing test SECOND
- Write minimal code to pass THIRD
- Refactor FOURTH

### SOLID Principles
- Each entity has ONE reason to change (SRP)
- Entities are open for extension, closed for modification (OCP)
- Value objects are immutable and interchangeable (LSP)
- Interfaces are specific to use cases (ISP)
- Depend on abstractions (ports), not implementations (DIP)

---

**This document defines WHAT the system does (business rules), NOT HOW it does it (technical implementation).**
