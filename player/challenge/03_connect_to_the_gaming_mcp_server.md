# Connect to the Game with MCP

Your goal is to let the player agent discover and call the game server's MCP tools as the player registered on this page. This turns the foundation agent into an authenticated participant that can start a quest, inspect its current mission, and submit answers.

## Game endpoint

Add the game-specific endpoint to the existing **C:\workshop\\.env** file:

```env
GAME_MCP_URL={{ game_mcp_url }}
GAME_API_KEY=<copy-from-this-player-page>
```

## Challenge

Integrate the MCP endpoint as an agent tool source, send **GAME_API_KEY** as an `Authorization: Bearer` header, and give the agent enough behavioral guidance to use game state rather than inventing progress. Treat server responses as authoritative and never expose the key in model context or logs.

## Expected outcome

- The agent discovers the game MCP tools at runtime.
- The MCP connection resolves the player created on this page without a `player_id` tool argument.
- The authenticated quest can be started.
- The agent can inspect the current mission and submit an answer.
- MCP errors remain visible and actionable.
- The MCP client closes cleanly when the application exits.

## Completion check

The server returns the authenticated quest state for {{ game_name }}, and the agent can make at least one valid game-tool call without passing identity as a tool argument.
