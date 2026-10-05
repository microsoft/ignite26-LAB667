# Integrate the Agent42 Transport Specialist

Your goal is to obtain transport recommendations from Agent42 over A2A. This matters because travel missions should consider route conditions, weather, and traffic instead of relying on a hard-coded choice.

## Specialist endpoint

Agent42 is available at:

```env
AGENT42_URL={{ agent42_url }}
```

## Challenge

Build and validate an A2A client interaction with Agent42 before adding it to the main player. The specialist request must contain enough route context to produce a defensible `car`, `walking`, or `bike` recommendation.

## Expected outcome

- The project can communicate with Agent42 through A2A.
- Route context reaches the specialist in a clear request.
- The response identifies a supported transport answer and rationale.
- Protocol and service failures are surfaced explicitly.
- The specialist client is suitable for reuse as a player-agent tool.

## Completion check

A standalone specialist request returns a valid transport recommendation that could be submitted to the game MCP server.
