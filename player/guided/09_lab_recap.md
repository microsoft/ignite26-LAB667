# Lab Recap

You played your quest to the end. Your player agent started the game, asked
Agent42 how to travel, looked up the answer in the city guide, read the secret
note, and got you through the door.

## What You Built

- A Python agent using the Microsoft Agent Framework and a model in Microsoft
   Foundry.
- A connection to the game server through MCP, with your private API key.
- Session logging so you can inspect model input, model output, tool calls,
   and tool results.
- An Agent42 tool, **ask_agent42**, that reaches the transport specialist over
   A2A.
- A Foundry IQ knowledge base over the {{ game_city }} city guide.
- A direct MCP connection to that knowledge base, with the
   **knowledge_base_retrieve** tool.
- A Note Reader that reads an image and answers with structured output,
   behind your own custom tool, **read_secret_note**.
- A chat loop that plays through the complete quest.

## How The Pieces Fit Together

The game server owns the quest state and exposes missions through MCP. Your
player agent decides what to do next and calls tools when it needs outside help.

Agent42 acts as a transport expert. When the game asks how to move through the
city, your agent asks Agent42 for a recommendation and submits that answer back
to the game server.

When the game asks a question about the city, your agent calls
**knowledge_base_retrieve** directly. The knowledge base searches the city
guide and writes an answer; your agent submits the answer to the game.

At the door, your agent calls **read_secret_note**. The Note Reader looks at the
picture of the note, detects the language, and returns the password as
structured output; your agent gives it to the host.

Your private API key keeps the same player and quest across runs. Logging lets
you see why the agent made each decision.

## What To Take Away

- MCP is useful when an agent needs to work with an external app or game state.
- A2A is useful when one agent should ask another agent for specialized help.
- Retrieval helps the agent answer questions from a trusted knowledge source.
- Structured output turns a model's answer into fields your code can use.
- Logging makes agent behavior easier to debug, explain, and improve.

## Next Steps

- Try another run and compare the session log with what happened in the game.
- Change the agent instructions and see how the tool choices change.
- Add another small tool to the player agent.
- Extend the city guide with more source material.
- Reuse the same MCP, A2A, retrieval, and logging pattern in your own
   agent project.