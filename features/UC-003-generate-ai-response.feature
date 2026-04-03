Feature: Generate AI Response
  As an AI agent
  I want to generate intelligent responses to caller speech
  So that I can have meaningful conversations

  Background:
    Given an active call is in progress
    And the ConversationSession contains previous conversation context

  Scenario: Generate response to simple question
    Given the caller asked "What is the weather today?"
    And an Utterance with this text exists
    When the AI processes the utterance
    Then an AIResponse entity is created
    And the AIResponse contains relevant reply text
    And the AIResponse is associated with the source Utterance
    And the AIResponse confidence is recorded
    And an AIResponseGenerated event is published

  Scenario: Generate streaming response (incremental chunks)
    Given the caller asked a complex question
    When the AI begins generating a response
    Then the AI creates partial AIResponse chunks
    And each chunk is published as an AIResponseGenerated event
    And each event is marked as "partial"
    When the AI completes the response
    Then a final AIResponseGenerated event is published
    And the event is marked as "complete"

  Scenario: Generate response with conversation context
    Given the caller previously asked "What's the weather?"
    And the AI responded "It's sunny today"
    When the caller asks "Will it rain tomorrow?"
    Then the AI uses previous context to understand the question
    And the AIResponse references weather topic
    And the response is contextually appropriate

  Scenario: Generate response requiring external data
    Given the caller asks "What's my account balance?"
    When the AI processes the request
    Then the AI recognizes the need for external data
    And the AI retrieves caller's account information
    And the AIResponse includes the actual account balance
    And the response is personalized to the caller

  Scenario: Handle ambiguous caller input
    Given the caller says "I need help"
    When the AI processes the vague request
    Then the AI generates a clarifying question
    And the AIResponse asks "What do you need help with?"
    And the response guides the conversation productively

  Scenario: Generate multi-turn conversation
    Given the caller asks "What services do you offer?"
    When the AI lists several services
    Then the AIResponse is structured appropriately
    And the caller can follow up with more questions
    And the conversation flow is natural

  Scenario: Handle caller providing information
    Given the AI asked "What's your account number?"
    When the caller says "It's 12345"
    Then the AI acknowledges the information
    And the AIResponse confirms "Got it, account 12345"
    And the information is stored in conversation context

  Scenario: Generate error recovery response
    Given the AI encountered an error retrieving data
    When the AI needs to respond to the caller
    Then the AIResponse gracefully explains the issue
    And the response offers alternatives
    And the conversation continues without abrupt failure

  # Edge Cases

  Scenario: Handle empty or unclear utterance
    Given the Utterance text is empty or only whitespace
    When the AI processes the utterance
    Then the AI generates a response asking caller to repeat
    And the AIResponse text is "I didn't catch that. Could you repeat?"

  Scenario: Handle very long utterance
    Given the caller speaks continuously for 60 seconds
    When the Utterance contains a very long speech
    Then the AI summarizes or chunks the response appropriately
    And the AIResponse addresses key points
    And the response length is reasonable for speech synthesis

  Scenario: Detect and handle sensitive information
    Given the caller mentions a credit card number
    When the AI processes the utterance
    Then the AI recognizes sensitive information
    And the AIResponse warns about security
    And the sensitive data is not logged or stored

  Scenario: Handle interruption while generating response
    Given the AI is generating a long response
    When the caller speaks while AI is thinking
    Then the AI detects the interruption
    And the current response generation is cancelled
    And a new AIResponse is generated for the new utterance

  Scenario: Generate response when LLM is unavailable
    Given the LLM service is temporarily unavailable
    When the AI attempts to generate a response
    Then the system uses a fallback response
    And the AIResponse explains the temporary issue
    And the call remains active

  Scenario: Handle response generation timeout
    Given the AI is generating a response
    When response generation exceeds 10 seconds
    Then the system times out the request
    And a fallback AIResponse is created
    And the response apologizes for the delay

  # Business Rules

  Rule: AIResponse must always be associated with an Utterance
    Scenario: No orphaned responses
      When an AIResponse is created
      Then it must reference a specific Utterance
      And the Utterance must exist in the same ConversationSession

  Rule: Response must be contextually appropriate
    Scenario: Maintain conversation coherence
      Given a conversation about account balances
      When the caller asks a follow-up question
      Then the AI uses conversation history
      And the response doesn't lose context
      And the topic transitions are logical

  Rule: Response generation must respect latency constraints
    Scenario: Generate response within time budget
      Given the caller finished speaking
      When the AI generates a response
      Then the first response token is available within 500ms
      And streaming continues without large gaps
      And perceived latency feels natural

  Rule: Responses must be safe and appropriate
    Scenario: Filter harmful content
      When the AI generates response text
      Then the text is checked for harmful content
      And inappropriate content is filtered
      And the final AIResponse is safe for all audiences

  Rule: AI must handle conversation failures gracefully
    Scenario: Graceful degradation
      Given a critical error occurs during response generation
      When the AI cannot generate a proper response
      Then a fallback response is provided
      And the caller is informed of the issue
      And the conversation can continue or end gracefully

  Rule: Streaming responses must be monotonic
    Scenario: Incremental response building
      Given a streaming response is being generated
      When partial chunks arrive
      Then each chunk extends previous content
      And text is never removed or contradicted
      And the final complete response is coherent
