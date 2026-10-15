# Mission 1: Get Ready and Start the Game

Your first mission is to prepare the development environment and build an agent
that can enter {{ game_name }}.

The situation is:

{{ game_story }}

## Objectives

1. Open Visual Studio Code from the Windows desktop and confirm that
   **C:\workshop** is the active workspace.
2. Use the PowerShell terminal in **C:\workshop** to verify the prepared Python
   environment and Microsoft Agent Framework packages.
3. Configure the supplied model deployment from Microsoft Foundry in the
   existing **C:\workshop\\.env** file.
4. Build a basic hello-world agent and prove that it can return a model
   response.
5. Start the game on this page, choose a nickname, and copy the private Player
   API key into **C:\workshop\\.env**.
6. Add the game MCP server to the agent:

   ```env
   GAME_MCP_URL={{ game_mcp_url }}
   GAME_API_KEY=<copy-from-this-player-page>
   ```

7. Authenticate MCP requests with `Authorization: Bearer <GAME_API_KEY>`.
8. Load the `game_play_prompt` instructions from the MCP server and use them as
   the agent's instructions.
9. Ask the agent to start or resume the game and inspect the first mission.

## Rules

- Do not put credentials in Python source, prompts, tool arguments, or logs.
- Treat MCP game state as authoritative; do not invent progress.
- Surface model, configuration, authentication, and MCP failures clearly.
- Close model and MCP clients cleanly.

## Completion check

The agent loads its instructions from MCP, starts the authenticated game, and
returns the first mission for the nickname registered on this page. The Player
timeline shows that the game has started.
