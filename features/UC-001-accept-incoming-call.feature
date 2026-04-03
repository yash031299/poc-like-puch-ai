Feature: Accept Incoming Phone Call
  As a telephone system
  I want to accept incoming calls from users
  So that they can interact with the AI agent

  Background:
    Given the voice AI system is running
    And the system is ready to accept connections

  Scenario: Successfully accept a new incoming call
    Given a caller dials the AI agent's phone number
    When the telephony provider routes the call to our service
    Then the system creates a new ConversationSession
    And the ConversationSession has a unique StreamIdentifier
    And the CallSession is in "initiated" state
    And a CallInitiated event is published
    And the system is ready to receive audio from the caller

  Scenario: Accept call with caller identification
    Given a caller with phone number "+1234567890" dials the AI agent
    When the call is connected
    Then the ConversationSession records the caller number as "+1234567890"
    And the ConversationSession records the dialed number
    And the call start timestamp is recorded

  Scenario: Accept call with custom routing parameters
    Given a caller dials the AI agent with custom parameters:
      | parameter   | value        |
      | language    | en-US        |
      | department  | sales        |
      | priority    | high         |
    When the call is connected
    Then the custom parameters are stored in the ConversationSession
    And the parameters are available for AI processing

  Scenario: Reject call when system is at capacity
    Given the system is already handling 10 concurrent calls
    And the maximum concurrent call limit is 10
    When a new caller attempts to connect
    Then the system rejects the connection
    And the caller receives a busy signal
    And a CallRejected event is published with reason "capacity_limit"

  Scenario: Reject call with invalid credentials (if auth is enabled)
    Given the system requires authentication
    When a call arrives without valid credentials
    Then the system rejects the connection
    And a CallRejected event is published with reason "unauthorized"

  Scenario: Accept call and determine audio format
    Given a caller initiates a connection
    When the telephony provider specifies audio format:
      | sample_rate | 16000     |
      | encoding    | PCM16LE   |
      | channels    | 1         |
    Then the ConversationSession configures audio format accordingly
    And all audio processing uses the specified format

  Scenario: Handle concurrent calls independently
    Given caller A is already connected
    When caller B initiates a new call
    Then the system creates a separate ConversationSession for caller B
    And caller A's session is unaffected
    And each session has a distinct StreamIdentifier

  # Edge Cases

  Scenario: Handle rapid disconnect after connection
    Given a caller initiates a connection
    When the caller disconnects before sending any audio
    Then the ConversationSession is created
    And the ConversationSession transitions to "ended" state immediately
    And a CallEnded event is published with reason "immediate_disconnect"
    And resources are properly cleaned up

  Scenario: Handle connection with missing metadata
    Given a call arrives without caller number information
    When the call is connected
    Then the system creates a ConversationSession
    And the caller number is recorded as "unknown"
    And the call proceeds normally

  # Business Rules

  Rule: StreamIdentifier must be globally unique
    Scenario: Ensure unique stream identifiers
      Given multiple calls are accepted
      Then each ConversationSession has a different StreamIdentifier
      And no two active or historical sessions share the same identifier

  Rule: Call initialization must be atomic
    Scenario: All or nothing call setup
      Given a call connection is being initialized
      When any setup step fails
      Then no ConversationSession is created
      And no partial state is persisted
      And the connection is cleanly rejected
