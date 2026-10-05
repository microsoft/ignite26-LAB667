# Integrate the Agent42 Transport Specialist

Your goal is to obtain transport recommendations from Agent42 over A2A. This matters because travel missions should consider route conditions, weather, and traffic instead of relying on a hard-coded choice.

## Specialist endpoint

Agent42 is available at:

```env
AGENT42_URL={{ agent42_url }}
```

## Challenge

Build and validate an A2A client interaction with Agent42 before adding it to the main player. Authenticate the request with **GAME_API_KEY** as an `Authorization: Bearer` header. The specialist request must contain enough route context to produce a defensible `car`, `walking`, or `bike` recommendation, but the private key must not enter the prompt or logs.

## Expected outcome

- The project can communicate with Agent42 through A2A.
- Agent42 authenticates the same Player API key used by the game MCP server.
- Route context reaches the specialist in a clear request.
- The response identifies a supported transport answer and rationale.
- The advice appears as an Agent42 event on the Player timeline.
- Protocol and service failures are surfaced explicitly.
- The specialist client is suitable for reuse as a player-agent tool.

## Completion check

A standalone authenticated specialist request returns a valid transport recommendation that could be submitted to the game MCP server, and the advice appears on the Player timeline.
