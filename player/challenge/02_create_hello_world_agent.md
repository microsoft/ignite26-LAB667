# Create the Foundation Agent

Your goal is to build the smallest useful Microsoft Agent Framework application that can accept a prompt and return a model response. This establishes the execution pattern that every later game capability will extend.

## Challenge

Design a Python entry point for the player agent with clear instructions, model configuration, asynchronous execution, and reliable resource cleanup. Keep the initial behavior intentionally small so later integrations remain easy to reason about.

## Expected outcome

- A Python agent starts from the workshop project.
- The agent responds to a simple prompt through the configured model.
- The application has an obvious place to add tools and context providers.
- Network clients and other resources close cleanly.
- Configuration and runtime failures are surfaced explicitly.

## Completion check

Running the player produces one successful agent response and exits without warnings or leaked resources.
