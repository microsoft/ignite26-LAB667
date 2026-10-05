# Orchestrate the Complete Player

Your goal is to combine authenticated game MCP tools, Agent42, city-guide retrieval, and safe session logging in one player agent. This is the integration point where the separate capabilities become an autonomous solution for the full adventure.

## Challenge

Design tool descriptions and agent instructions that lead the player to choose the right specialist for each mission, submit only supported answers, and continue until the quest reaches a terminal state. Use **GAME_API_KEY** as the bearer credential for both MCP and Agent42 without adding it to model instructions, tool arguments, or logs.

## Expected outcome

- Travel missions are delegated to Agent42.
- City questions are delegated to the retrieval-backed guide.
- MCP remains the authority for mission state and accepted answers.
- The same Player API key authenticates MCP and Agent42 throughout the run.
- MCP tools do not accept a `player_id` argument.
- Agent42 advice and game progress appear on the Player timeline.
- Every significant decision and tool call is logged.
- The private Player API key is never logged or exposed to the model.
- The orchestration handles recoverable failures without corrupting game state.

## Completion check

The integrated agent advances through both travel and question missions without manual answer injection and can explain which tool supported each submitted answer.
