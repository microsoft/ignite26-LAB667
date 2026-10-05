# Step 3: Connect To The Gaming MCP Server

In this exercise, you connect the agent to the Lost in the City game server
through MCP so it can start sessions and call game actions as tools. This matters
because MCP turns the game into something the agent can operate instead of just
talking about.

> [!Hint] 🖥️ **In VS Code** — this whole step happens in the VS Code editor and terminal.

The game exposes its actions as MCP tools and the game play agent prompt as an
MCP prompt. In the agent code this connection is the **MCPStreamableHTTPTool**
named **game_mcp**.

Open the existing **.env** file and confirm the game MCP URL is
already there. Copy the private API key shown on this Player page and add it
beside the URL:

```env
GAME_MCP_URL={{ game_mcp_url }}
GAME_API_KEY=<copy-from-this-player-page>
```

> [!Hint] Make sure the URL ends in **/{{ game_slug }}/mcp** so you connect to **{{ game_name }}**.
> Keep **GAME_API_KEY** private. It identifies your player and authorizes every
> game action. Do not paste it into chat, source code, or session logs.

Go back to **agent.py**. At the top of **agent.py**, update the existing
Microsoft Agent Framework import so it also imports **MCPStreamableHTTPTool**:

```python
from agent_framework import Agent, MCPStreamableHTTPTool
```

Inside **main()**, keep **async with client.client:** from Step 2. Within that
block, add a second context manager before the **Agent(...)** call:

```python-notype
async with MCPStreamableHTTPTool(
	name="Gaming MCP Server",
	url=os.environ["GAME_MCP_URL"],
	static_headers={
		"Authorization": f"Bearer {os.environ['GAME_API_KEY']}",
	},
) as game_mcp:
	game_play_prompt = await game_mcp.get_prompt("game_play_prompt")
```

The MCP context manager connects when the block starts and closes the connection
when it ends. Do not add separate **connect()** or **close()** calls.

> [!Hint] MCP servers can expose more than tools. They can also expose prompts
> that client agents load and use as instructions. In this workshop, the game
> server owns the game play prompt so the agent and game stay in sync.

The first line inside the MCP block gets the game play prompt from the server:

```python
game_play_prompt = await game_mcp.get_prompt("game_play_prompt")
```

Still in **agent.py**, inside the MCP block, update the existing **Agent(...)** call. Keep the client and name you already have, use **game_play_prompt** for the instructions, and add the
**tools=[game_mcp]** line:

```python
agent = Agent(
	client=client,
	name="Game Play Agent",
	instructions=game_play_prompt,
	tools=[game_mcp],
)
```

Create a chat session and start the game:

```python
session = agent.create_session()
response = await agent.run("start the game", session=session)
print(response.text)
```

Keep all three lines above inside the MCP block. Both connections are closed
automatically after the run, even if loading the prompt or calling the agent fails.

Run the agent from the VS Code terminal:

```powershell
python agent.py
```

> **Checkpoint:** the terminal may show experimental warning messages from the
> framework, then the agent should welcome you by the nickname registered on
> this Player page. The agent never asks for or prints your API key.

> [!Hint] Check for indentation if you run into errors. Python is indentation
> sensitive, and as such you may run into errors if blocks are not
> properly indented. Look at the Sample below if you need help with this.

## Full agent.py Sample

If you want to compare your file with a complete version, **agent.py** should now
look like this:

```python-notype
"""Game play agent using Microsoft Agent Framework, Azure OpenAI, and MCP."""

import asyncio
import os
from pathlib import Path

from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv

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
            static_headers={
                "Authorization": f"Bearer {os.environ['GAME_API_KEY']}",
            },
        ) as game_mcp:
            game_play_prompt = await game_mcp.get_prompt("game_play_prompt")

            agent = Agent(
                client=client,
                name="Game Play Agent",
                instructions=game_play_prompt,
                tools=[game_mcp],
            )

            session = agent.create_session()
            response = await agent.run("start the game", session=session)
            print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
```

## What You Learned

You connected the agent to an MCP server with bearer authentication, loaded the
game play prompt, exposed the game actions as tools, and linked every action to
the player created on this page.