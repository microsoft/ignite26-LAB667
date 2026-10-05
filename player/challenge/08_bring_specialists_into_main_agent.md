# Orchestrate the Complete Player

Your goal is to combine game MCP tools, Agent42, city-guide retrieval, memory, and logging in one player agent. This is the integration point where the separate capabilities become an autonomous solution for the full adventure.

## Challenge

Design tool descriptions and agent instructions that lead the player to choose the right specialist for each mission, submit only supported answers, preserve its identity, and continue until the quest reaches a terminal state.

## Expected outcome

- Travel missions are delegated to Agent42.
- City questions are delegated to the retrieval-backed guide.
- MCP remains the authority for mission state and accepted answers.
- The same player ID is used throughout the run.
- Every significant decision and tool call is logged.
- The orchestration handles recoverable failures without corrupting game state.

## Completion check

The integrated agent advances through both travel and question missions without manual answer injection and can explain which tool supported each submitted answer.
