# Arrived: Complete the Game

Your agent has solved the city-guide question. One final journey remains:
ask Agent42 for help, choose how to travel, and arrive at the event destination.

> [!Hint] 🖥️ **In VS Code** — keep the player running in the terminal from the
> previous lesson. If you stopped it, run `python agent.py` again.

## Finish the Final Travel Mission

1. Ask the player agent to continue the quest.
2. When MCP presents the final travel mission, ask the agent to get help from
   **Agent42**.
3. Read Agent42's route advice and give the agent your final choice of `car`,
   `walking`, or `bike`.
4. Let the agent submit that choice and the private route metadata to MCP.
5. Wait for the full arrival narration and confirmation that the quest is
   complete.
6. Return to this Player page and confirm that the timeline shows the final
   Agent42 route and completed mission.

> **Checkpoint:** MCP confirms that you arrived at the event destination, the
> final Agent42 route appears on the Player timeline, and no private API key or
> route metadata appears in the conversation.

## Lab Recap

You built a working player agent for the **Lost in the City** workshop. The
agent can start or resume a game, choose tools, ask other services for help,
retrieve guidebook knowledge, remember useful state, and log what happened.

## What You Built

- A Python agent using the Microsoft Agent Framework.
- A connection to the game server through MCP.
- A memory file that keeps the player ID between runs.
- Session logging so you can inspect model input, model output, tool calls,
   and tool results.
- A separate Agent42 test client for transport recommendations.
- An Agent42 tool inside the main player agent.
- A city guide specialist that answers questions from the San Francisco guide.
- A city guide tool inside the main player agent.
- A final run that plays through the complete quest.

## How The Pieces Fit Together

The game server owns the quest state and exposes missions through MCP. Your
player agent decides what to do next and calls tools when it needs outside help.

Agent42 acts as a transport expert. When the game asks how to move through the
city, your agent asks Agent42 for a recommendation and submits that answer back
to the game server.

The city guide agent acts as a retrieval specialist. When the game asks a
guidebook question, your agent calls the guide tool, finds the relevant city
knowledge, and submits the answer.

Memory keeps the same player session alive across runs. Logging lets you see
why the agent made each decision.

## What To Take Away

- MCP is useful when an agent needs to work with an external app or game state.
- A2A is useful when one agent should ask another agent for specialized help.
- Retrieval helps the agent answer questions from a trusted knowledge source.
- Memory turns repeated runs into a continued session instead of a fresh start.
- Logging makes agent behavior easier to debug, explain, and improve.

## Next Steps

- Try another run and compare the session log with what happened in the game.
- Change the agent instructions and see how the tool choices change.
- Add another small tool to the player agent.
- Extend the city guide with more source material.
- Reuse the same MCP, A2A, retrieval, memory, and logging pattern in your own
   agent project.