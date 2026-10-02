# Step 4: Add Memory For The Player ID

In this exercise, you add lightweight memory so the agent can save the
**player_id** returned by the game. This matters because future runs should resume
the same player session instead of registering a new player every time.

> [!Hint] 🖥️ **In VS Code** — this whole step happens in the VS Code editor and terminal.

Go back to **agent.py**. At the top of **agent.py**, combine these imports with the
other imports:

```python
import json
from pathlib import Path
from typing import Any

from agent_framework import AgentSession, ContextProvider, SessionContext, SupportsAgentRun, tool
```

In **agent.py**, add the memory file constant near the top of the file, after the
imports and before **main()**. Keep the existing **load_dotenv(...)** call inside
**main()**:

```python
MEMORY_FILE = Path(__file__).resolve().with_name("memory.json")
```

The memory file lives beside **agent.py**, not in whichever folder the terminal
happens to use.

> [!Hint] A context provider is a small hook that runs before the model gets a
> turn. It can add useful context to the agent instructions, such as remembered
> state from a previous run. In this step, the context provider reads
> **memory.json** and tells the agent which **player_id** to resume.

In **agent.py**, add this context provider class after the memory file constant
and before **main()**. It injects the saved player ID before each model run:

```python-notype
class PlayerContextProvider(ContextProvider):
	async def before_run(
		self,
		*,
		agent: SupportsAgentRun,
		session: AgentSession,
		context: SessionContext,
		state: dict[str, Any],
	) -> None:
		if MEMORY_FILE.exists():
			memory = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
			if not isinstance(memory, dict):
				raise ValueError(f"{MEMORY_FILE} must contain a JSON object.")
			player_id = memory.get("player_id")
			if player_id is not None:
				if not isinstance(player_id, str) or not player_id.strip():
					raise ValueError(f"{MEMORY_FILE} must contain a non-empty player_id string.")
				context.extend_instructions(self.source_id, f"From memory: player_id: {player_id}")
```

> [!Hint] Tool calling lets the model ask your Python code to do a specific
> action. The model decides when the tool is needed, passes arguments to it, and
> receives the tool result back in the conversation. In this step, the tool gives
> the agent a controlled way to save the **player_id** after the game registers a
> player.

In **agent.py**, add this tool function below the context provider class. The
model can call it after registration to save the player ID:

```python
@tool(description="Save the player_id returned after registration")
async def save_player_id(player_id: str) -> str:
	if not player_id.strip():
		raise ValueError("player_id must not be empty.")
	MEMORY_FILE.write_text(json.dumps({"player_id": player_id}), encoding="utf-8")
	return f"Player ID {player_id} saved."
```

Inside **main()**, within the existing MCP context block, update the **Agent(...)** call. Keep
**instructions=game_play_prompt** and the game MCP tool, then add both the memory
tool and context provider:

```python
agent = Agent(
	client=client,
	name="Game Play Agent",
	instructions=game_play_prompt,
	tools=[game_mcp, save_player_id],
	context_providers=[PlayerContextProvider(source_id="player-memory")],
)
```

Still inside **main()**, update the code after **session = agent.create_session()**
so the agent starts the game, then sends your name in the same session:

```python
response = await agent.run("start the game", session=session)
print(response.text)

response = await agent.run("My name is <Your Name>", session=session)
print(response.text)
```

Replace **<Your Name>** with your real name before running **agent.py**.

## Full agent.py Sample

If you want to compare your file with a complete version, **agent.py** should now
look like this:

```python-notype
"""Game play agent using Microsoft Agent Framework, Azure OpenAI, and MCP."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from agent_framework import (
	Agent,
	AgentSession,
	ContextProvider,
	MCPStreamableHTTPTool,
	SessionContext,
	SupportsAgentRun,
	tool,
)
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv

MEMORY_FILE = Path(__file__).resolve().with_name("memory.json")


class PlayerContextProvider(ContextProvider):
	async def before_run(
		self,
		*,
		agent: SupportsAgentRun,
		session: AgentSession,
		context: SessionContext,
		state: dict[str, Any],
	) -> None:
		if MEMORY_FILE.exists():
			memory = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
			if not isinstance(memory, dict):
				raise ValueError(f"{MEMORY_FILE} must contain a JSON object.")
			player_id = memory.get("player_id")
			if player_id is not None:
				if not isinstance(player_id, str) or not player_id.strip():
					raise ValueError(f"{MEMORY_FILE} must contain a non-empty player_id string.")
				context.extend_instructions(self.source_id, f"From memory: player_id: {player_id}")


@tool(description="Save the player_id returned after registration")
async def save_player_id(player_id: str) -> str:
	if not player_id.strip():
		raise ValueError("player_id must not be empty.")
	MEMORY_FILE.write_text(json.dumps({"player_id": player_id}), encoding="utf-8")
	return f"Player ID {player_id} saved."


async def main() -> None:
	load_dotenv(Path(__file__).with_name(".env"), override=True)

	client = OpenAIChatClient(
		azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
		api_key=os.environ["AZURE_OPENAI_API_KEY"],
		model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
	)

	async with client.client:
		async with MCPStreamableHTTPTool(
			name="Gaming MCP Server",
			url=os.environ["GAME_MCP_URL"],
		) as game_mcp:
			game_play_prompt = await game_mcp.get_prompt("game_play_prompt")

			agent = Agent(
				client=client,
				name="Game Play Agent",
				instructions=game_play_prompt,
				tools=[game_mcp, save_player_id],
				context_providers=[PlayerContextProvider(source_id="player-memory")],
			)

			session = agent.create_session()
			response = await agent.run("start the game", session=session)
			print(response.text)

			response = await agent.run("My name is <Your Name>", session=session)
			print(response.text)


if __name__ == "__main__":
	asyncio.run(main())
```

> **Checkpoint:** after the second **agent.run(...)** call, the terminal should
> show your new **player_id** and a message that says **Say START when you are
> ready**. The **C:\workshop\memory.json** file should contain the saved
> **player_id**. On the next run, the agent should resume instead of registering
> a new player.

> [!Hint] If **memory.json** contains invalid JSON, a non-object value, or a
> blank/non-string player ID, the agent reports an error instead of silently
> registering another player. Correct the saved file before retrying. A missing
> file or an empty JSON object means there is no remembered player.

> [!Hint] Look at the big screen in the room. Your name should now appear in the
> player list.

## What You Learned

You added lightweight memory with a context provider and a save tool so the
agent can remember its **player_id** between runs.
