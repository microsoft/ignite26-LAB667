# Connect to the Game with MCP

Your goal is to let the player agent discover and call the game server's MCP tools. This turns the foundation agent into an active participant that can register, start a quest, inspect its current mission, and submit answers.

## Game endpoint

Add the game-specific endpoint to the existing **C:\workshop\\.env** file:

```env
GAME_MCP_URL={{ game_mcp_url }}
```

## Challenge

Integrate the MCP endpoint as an agent tool source and give the agent enough behavioral guidance to use game state rather than inventing progress. Treat server responses as authoritative.

## Expected outcome

- The agent discovers the game MCP tools at runtime.
- A player can be registered and a quest can be started.
- The agent can inspect the current mission and submit an answer.
- MCP errors remain visible and actionable.
- The MCP client closes cleanly when the application exits.

## Completion check

The server returns a real player ID and quest state for {{ game_name }}, and the agent can make at least one valid game-tool call.
