Feature: Handle Call Termination
  As a voice AI system
  I want to properly handle call termination
  So that resources are cleaned up and state is finalized

  Background:
    Given an active call is in progress

  Scenario: Caller hangs up normally
    Given the conversation has completed successfully
    When the caller disconnects
    Then the system detects the disconnection
    And the CallSession transitions to "ended" state
    And a CallEnded event is published
    And the event reason is "caller_hung_up"
    And the call duration is recorded
    And all resources for the call are released

  Scenario: System terminates call due to error
    Given an active call encounters an unrecoverable error
    When the system decides to terminate the call
    Then the CallSession is marked as ended
    And a CallEnded event is published
    And the event reason is "system_error"
    And the error details are logged
    And the caller receives appropriate notification
    And resources are cleaned up

  Scenario: Call terminates due to timeout
    Given the caller has been silent for 5 minutes
    When the inactivity timeout expires
    Then the system initiates call termination
    And the CallSession is ended
    And a CallEnded event is published
    And the event reason is "timeout_inactivity"
    And resources are released

  Scenario: Normal conversation completion
    Given the AI and caller have completed their conversation
    When the AI says "Is there anything else I can help with?"
    And the caller responds "No, thank you"
    Then the AI says "Goodbye, have a great day!"
    And the system waits for caller to hang up
    And when the caller hangs up, resources are cleaned up

  Scenario: Maximum call duration exceeded
    Given a call has been active for 60 minutes
    And the maximum call duration is 60 minutes
    When the duration limit is reached
    Then the system warns the caller
    And the system initiates graceful termination
    And the CallSession is ended
    And a CallEnded event is published with reason "max_duration_exceeded"

  Scenario: Cleanup conversation state
    Given a call is ending
    When the CallSession transitions to "ended"
    Then all AudioChunks are marked as processed
    And all Utterances are finalized
    And all AIResponses are marked as complete
    And no new entities can be added to the ConversationSession
    And the conversation history is persisted (if configured)

  Scenario: Release external service connections
    Given a call is using STT, LLM, and TTS services
    When the call ends
    Then all service connections are gracefully closed
    And any ongoing streaming requests are cancelled
    And service resources are released
    And no orphaned connections remain

  # Edge Cases

  Scenario: Handle sudden network disconnection
    Given an active call is in progress
    When the network connection is lost abruptly
    Then the system detects the disconnection
    And the CallSession is marked as ended
    And a CallEnded event is published with reason "network_disconnected"
    And cleanup happens even without graceful termination signal
    And resources are released within 30 seconds

  Scenario: Handle call termination during AI response
    Given the AI is speaking to the caller
    When the caller hangs up mid-response
    Then the audio streaming is immediately stopped
    And the CallSession is ended
    And any ongoing synthesis is cancelled
    And resources are cleaned up

  Scenario: Handle call termination during caller speech
    Given the caller is speaking
    When the connection is lost
    Then accumulated audio is processed if possible
    And the final partial Utterance is recorded
    And the CallSession is ended normally
    And resources are released

  Scenario: Handle multiple termination signals
    Given the system is terminating a call
    When another termination signal is received
    Then the system ignores duplicate termination
    And cleanup is performed only once
    And no errors are raised

  Scenario: Handle cleanup failure for one resource
    Given a call is terminating
    When releasing one resource fails
    Then other resources are still cleaned up
    And the failure is logged
    And the CallSession still transitions to "ended"
    And the system remains stable

  Scenario: Terminate call when telephony provider fails
    Given the telephony provider connection is lost
    When the system detects the failure
    Then local resources are cleaned up
    And the CallSession is marked as ended
    And a CallEnded event is published with reason "provider_failure"

  # Business Rules

  Rule: Call termination must be idempotent
    Scenario: Multiple termination attempts
      Given a call is being terminated
      When termination is triggered multiple times
      Then the call ends exactly once
      And cleanup happens exactly once
      And no errors are raised from duplicate terminations

  Rule: Resources must be released within time limit
    Scenario: Timely resource cleanup
      Given a call has ended
      When cleanup begins
      Then all resources are released within 30 seconds
      And the system is ready to accept new calls
      And no resources are leaked

  Rule: Call duration must be accurately recorded
    Scenario: Precise duration tracking
      Given a call starts at timestamp T1
      And the call ends at timestamp T2
      Then the recorded duration is T2 - T1
      And the duration is included in CallEnded event
      And the duration precision is at least 1 second

  Rule: Conversation state must be finalized
    Scenario: Immutable completed conversation
      Given a call has ended
      When the ConversationSession is finalized
      Then no entities can be added or modified
      And the conversation is in a consistent state
      And all pending operations are completed or cancelled

  Rule: Cleanup must handle failures gracefully
    Scenario: Resilient cleanup process
      Given cleanup of resource A fails
      When cleanup continues for resources B and C
      Then B and C are successfully cleaned up
      And the failure of A is logged
      And the system remains operational

  Rule: Events must be published even on error
    Scenario: Always publish CallEnded event
      Given a call is ending for any reason
      Then a CallEnded event must be published
      And the event includes the termination reason
      And the event is published before resources are released
      And downstream systems are notified

  Rule: Graceful termination is preferred
    Scenario: Polite conversation ending
      Given the conversation is naturally concluding
      When the system can control termination
      Then the AI says goodbye appropriately
      And the caller has opportunity to hang up first
      And only if the caller doesn't hang up, system terminates

  Rule: Orphaned resources must be prevented
    Scenario: No resource leaks
      Given a call terminates abnormally
      When cleanup may be incomplete
      Then a background cleanup process runs
      And any orphaned resources are found and released
      And the system tracks resource usage
      And resource leaks are detected and resolved
