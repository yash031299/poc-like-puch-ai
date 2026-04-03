Feature: Manage Call Session
  As a voice AI system
  I want to manage the complete lifecycle of a call session
  So that conversation state is tracked and maintained correctly

  Background:
    Given the voice AI system is running

  Scenario: Initialize new call session
    Given a new call is connecting
    When the ConversationSession is created
    Then it contains a CallSession entity
    And the CallSession has a unique StreamIdentifier
    And the CallSession state is "initiated"
    And the session start time is recorded
    And the session is ready to accept audio

  Scenario: Transition session state through lifecycle
    Given a ConversationSession exists
    When the first audio arrives
    Then the CallSession state transitions to "active"
    When the call is terminated
    Then the CallSession state transitions to "ended"

  Scenario: Track conversation entities within session
    Given an active ConversationSession
    When AudioChunks are received
    Then they are added to the session's AudioChunk collection
    When Utterances are created
    Then they are added to the session's Utterance collection
    When AIResponses are generated
    Then they are added to the session's AIResponse collection
    When SpeechSegments are synthesized
    Then they are added to the session's SpeechSegment collection

  Scenario: Maintain conversation context
    Given a ConversationSession with previous exchanges
    When a new Utterance is created
    Then the AI can access previous Utterances
    And the AI can access previous AIResponses
    And the conversation context flows naturally

  Scenario: Query session state
    Given an active ConversationSession
    When querying session status
    Then the current state is returned (initiated/active/ended)
    And the session duration is available
    And the number of exchanges is known
    And the caller information is accessible

  Scenario: Retrieve conversation history
    Given a ConversationSession with multiple exchanges
    When requesting conversation history
    Then all Utterances are returned in chronological order
    And all AIResponses are returned in chronological order
    And the history represents the complete conversation

  Scenario: Enforce aggregate boundaries
    Given a ConversationSession aggregate
    When external code attempts to access entities
    Then access is only allowed through the aggregate root
    And entities cannot be modified outside the aggregate
    And consistency is maintained within the aggregate

  # Edge Cases

  Scenario: Handle concurrent operations on same session
    Given an active ConversationSession
    When multiple operations occur simultaneously:
      | operation             | timing |
      | Add AudioChunk        | T+0ms  |
      | Create Utterance      | T+10ms |
      | Generate AIResponse   | T+15ms |
    Then all operations complete successfully
    And the session state remains consistent
    And no race conditions occur

  Scenario: Prevent adding entities to ended session
    Given a ConversationSession in "ended" state
    When attempting to add new AudioChunk
    Then the operation is rejected
    And an error is raised indicating session is ended
    And the session state is not modified

  Scenario: Handle session timeout during activity
    Given a ConversationSession with inactivity timeout of 5 minutes
    When no activity occurs for 5 minutes
    Then the session transitions to "ended" automatically
    And a timeout event is published
    And resources are cleaned up

  Scenario: Recover from inconsistent session state
    Given a ConversationSession in an inconsistent state
    When the inconsistency is detected
    Then the session is marked as corrupted
    And the call is gracefully terminated
    And the issue is logged for investigation
    And the system remains stable

  Scenario: Handle session with very long duration
    Given a ConversationSession that has been active for 2 hours
    When querying session status
    Then the system handles the long duration correctly
    And memory usage remains stable
    And all operations continue functioning
    And no performance degradation occurs

  Scenario: Export session data for analytics
    Given a completed ConversationSession
    When exporting session data
    Then all entities are serialized correctly
    And the data includes metadata and timestamps
    And the export is in a standard format (JSON/XML)
    And sensitive data is redacted if required

  # Business Rules

  Rule: Session must maintain referential integrity
    Scenario: All entities reference valid session
      Given a ConversationSession
      When entities are added
      Then every AudioChunk references the session
      And every Utterance references the session
      And every AIResponse references the session
      And every SpeechSegment references the session
      And no orphaned entities exist

  Rule: Session state transitions must be valid
    Scenario: Enforce valid state transitions
      Given a CallSession in "initiated" state
      Then it can transition to "active"
      And it can transition to "ended"
      But it cannot transition back to "initiated"
      When in "active" state
      Then it can transition to "ended"
      But it cannot transition to "initiated"
      When in "ended" state
      Then no further state transitions are allowed

  Rule: Session must be thread-safe
    Scenario: Concurrent access safety
      Given multiple threads accessing a ConversationSession
      When concurrent reads and writes occur
      Then all operations are serialized correctly
      And the session state remains consistent
      And no data corruption occurs

  Rule: Session identifiers must be globally unique
    Scenario: Unique session identification
      Given multiple ConversationSessions are created
      Then each has a different StreamIdentifier
      And identifiers are not reused
      And sessions can be uniquely identified at any time

  Rule: Session must track all conversation turns
    Scenario: Complete conversation history
      Given a ConversationSession with multiple turns
      Then every caller speech (Utterance) is tracked
      And every AI response (AIResponse) is tracked
      And the chronological order is preserved
      And no conversation turns are lost

  Rule: Session must enforce business invariants
    Scenario: Aggregate invariant enforcement
      When an Utterance is created without AudioChunks
      Then the operation is rejected
      When an AIResponse is created without an Utterance
      Then the operation is rejected
      When a SpeechSegment is created without an AIResponse
      Then the operation is rejected
      And the aggregate ensures business rules are satisfied

  Rule: Session must handle resource limits
    Scenario: Session size limits
      Given a ConversationSession
      When the session contains 1000 AudioChunks
      Then the system may warn about size
      When the session exceeds maximum entities (10,000)
      Then older entities may be archived
      And essential conversation flow is maintained
      And memory usage is bounded

  Rule: Session cleanup must be complete
    Scenario: No partial cleanup
      Given a ConversationSession is being cleaned up
      When cleanup is initiated
      Then all entities are released atomically
      And either all resources are cleaned or none are
      And the session is either fully ended or remains active
      And no intermediate inconsistent states exist

  Rule: Session must be observable
    Scenario: Monitor session health
      Given an active ConversationSession
      Then the system can query session health
      And metrics are available (duration, entity counts, state)
      And anomalies can be detected (e.g., too many audio chunks)
      And health checks can trigger alerts if needed
