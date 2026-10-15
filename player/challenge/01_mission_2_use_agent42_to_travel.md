# Mission 2: Use Agent42 to Travel

The game has given you a travel situation. Extend the player with an A2A
specialist called **Agent42** and use its recommendation to reach the first
checkpoint.

## Specialist endpoint

Add the shared Agent42 endpoint to **C:\workshop\\.env**:

```env
AGENT42_URL={{ agent42_url }}
```

## Objectives

1. Build an authenticated A2A client for Agent42.
2. Send the same `GAME_API_KEY` as an `Authorization: Bearer` header.
3. Expose Agent42 to the main player as a focused travel tool.
4. Give Agent42 the complete origin, destination, and travel situation returned
   by the game MCP server.
5. Use Agent42's supported `car`, `walking`, or `bike` recommendation and route
   reference when submitting the movement answer to MCP.
6. Continue until the game confirms arrival at the first checkpoint and reveals
   the question and resources for the next mission.

## Rules

- Never place the Player API key in the A2A prompt or model context.
- Do not hard-code a transport answer.
- Do not claim arrival until MCP accepts the movement answer.
- Preserve Agent42 failures and timeouts as actionable errors.

## Completion check

Agent42 returns a defensible route recommendation, the agent submits it to MCP,
and the Player timeline shows both the Agent42 advice and arrival at the first
checkpoint.
