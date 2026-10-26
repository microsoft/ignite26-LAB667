# Add The City Guide To Your Agent

In this exercise, you give your game agent its second specialist: the **City
Guide** knowledge base. In the previous mission, you stopped at a question about
the city. Now your game agent gets the **knowledge_base_retrieve** tool, looks
up the answer in the city guide, and travels on to the event.

> [!Hint] 🖥️ **In VS Code** — this whole step happens in the VS Code editor and terminal.

## Add the City Guide to the game agent

Your agent needs three changes. Read through them first; at the end you replace
**agent.py** with the complete code.

### 1. Import the City Guide

```python-read
from agent_city_guide import build_city_guide_tool
```

This loads the builder from **agent_city_guide.py**, the file you created in the
previous mission.

### 2. Open the City Guide connection

```python-read
async with (
    client.client,
    game_mcp,
    build_agent42_agent() as agent42,
    build_city_guide_tool() as guide_tool,
):
    ...
```

The **async with** block now opens four connections: the model, the game server,
Agent42, and the City Guide knowledge base. It closes all of them when the block
ends, even if something fails.

### 3. Add the City Guide to the tools

```python-read
agent = Agent(
    client=client,
    name="Game Play Agent",
    instructions=game_play_prompt,
    tools=[game_mcp, agent42_tool, guide_tool],
    middleware=[agent_mw, chat_mw, function_mw],
)
```

The City Guide connection is already a tool, so it goes straight into the list
and gives the agent **knowledge_base_retrieve**, next to **ask_agent42**. The
model picks the right tool for each mission.

## Replace agent.py

Now put the three changes together. Replace everything in **agent.py** with the
code below and save the file. It's the same agent you played with in the
previous mission, now with the City Guide.

```python-notype
"""Game play agent using Microsoft Agent Framework with Microsoft Foundry."""

import asyncio
import os
from pathlib import Path

from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv

from agent_agent42 import build_agent42_agent, build_agent42_tool
from agent_city_guide import build_city_guide_tool
from log import build_logging_middleware, open_session_log

GREEN = "\033[32m"
PURPLE = "\033[35m"
RESET = "\033[0m"


async def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"), override=True)

    client = OpenAIChatClient(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    )

    log_path = open_session_log()
    print(f"Session log: {log_path}")
    agent_mw, chat_mw, function_mw = build_logging_middleware(log_path)

    game_mcp = MCPStreamableHTTPTool(
        name="Gaming MCP Server",
        url=os.environ["GAME_MCP_URL"],
        static_headers={"Authorization": f"Bearer {os.environ['GAME_API_KEY']}"},
    )

    async with (
        client.client,
        game_mcp,
        build_agent42_agent() as agent42,
        build_city_guide_tool() as guide_tool,
    ):
        game_play_prompt = await game_mcp.get_prompt("game_play_prompt")
        agent42_tool = build_agent42_tool(agent42)

        agent = Agent(
            client=client,
            name="Game Play Agent",
            instructions=game_play_prompt,
            tools=[game_mcp, agent42_tool, guide_tool],
            middleware=[agent_mw, chat_mw, function_mw],
        )

        print("Chat with Game Play Agent (type 'exit' or 'quit' to stop)\n")
        session = agent.create_session()
        response = await agent.run("start the game", session=session)
        print(f"{PURPLE}Agent:{RESET} {response.text}\n")

        while True:
            try:
                user_input = input(f"{GREEN}You:{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break
            response = await agent.run(user_input, session=session)
            print(f"{PURPLE}Agent:{RESET} {response.text}\n")


if __name__ == "__main__":
    asyncio.run(main())
```

## Answer the city question

Run the agent from the VS Code terminal:

```powershell
python agent.py
```

The agent picks up your quest at the question about the city. Ask it to look up
the answer, and it calls **knowledge_base_retrieve**. Here is what the
conversation looks like. The agent's own words can change a little from run to
run:

```output-read
Chat with Game Play Agent (type 'exit' or 'quit' to stop)

Agent: Welcome back, {{ player_name }}. {{ player_quest_question }}

You: Can you look this up in the city guide?

Agent: According to the city guide, <answer>. I submitted it, and it is correct. <next scene of your quest>
```

> [!Hint] Look at the **Live progress** bar at the top of this page. The
> completed question mission appears there. Open the newest session log to see
> the call to **knowledge_base_retrieve** and what came back.

## Travel to the event

The next journey takes you from your current stop to the event. It's a travel
mission again, so type **HELP**, and the agent asks Agent42 for advice. Choose
how to travel, and the agent submits your choice:

```output-read
Agent: <next scene>. What transport will you take: car, walking, or bike?

You: HELP

Agent: I asked Agent42. <weather, route, and travel times>. Agent42 recommends <car, bike, or walking>. Do you want to go that way?

You: Yes

Agent: <arrival at the event>. Before you go in, I need the secret password.
```

## A password at the door

You made it to the event, but the host at the entrance asks for a secret
password. You remember the folded piece of paper you got at the start of your
quest. It's written in a strange language, and your agent has no way to read it
yet.

Don't let it guess. Type **exit** to stop the agent. Your progress is saved on
the game server, so you continue from the door in the next mission.

## What You Learned

Your game agent now has two specialists. Agent42 is a separate agent that your
agent reaches over A2A through the **ask_agent42** tool. The City Guide is a
knowledge base that your agent reaches directly over MCP through
**knowledge_base_retrieve**. Your agent decides by itself which one to use for
each mission.

Your agent can now handle travel missions and questions about the city, but it
can't read the note. In the next mission, you build a **Note Reader** that reads
the note for you.
