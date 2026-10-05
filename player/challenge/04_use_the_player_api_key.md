# Use the Player API Key

Your goal is to make every game request act as the player created on this page
without passing identity through prompts or MCP tool arguments. This matters
because the private API key is now both the player identity and the bearer
credential.

## Challenge

Start a game with a nickname on this page, store the generated key in the
existing **C:\workshop\.env** file as `GAME_API_KEY`, and configure the MCP HTTP
connection to send `Authorization: Bearer <key>`. Keep the key out of source
code, model context, tool arguments, and logs.

## Expected outcome

- The browser remembers the key and can reopen the same Player timeline.
- The MCP server resolves the player entirely from the bearer header.
- Game tools no longer accept or return a private `player_id`.
- An invalid or missing key is rejected before any MCP tool executes.
- Refreshing the Player page and restarting the agent both continue the same
  game.

## Completion check

Two consecutive agent runs connect to the same nickname and quest, while the
Player timeline continues to update without creating another player.
