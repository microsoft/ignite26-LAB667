# Bring the Specialists In

In this exercise, you combine the authenticated game MCP connection, Agent42,
the city guide, and session logging in one conversational agent. The final
player must coordinate every specialist while all game and
transport activity stays connected to the Player timeline.

> [!Hint] 🖥️ **In VS Code** — replace **C:\workshop\agent.py** with the complete
> version below.

```python-notype
"""Game play agent using Microsoft Agent Framework with Azure OpenAI."""

import asyncio
import os
from pathlib import Path

from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv

from agent_agent42 import build_agent42_agent, build_agent42_tool
from agent_city_guide import build_city_guide_agent, build_city_guide_tool
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
        build_city_guide_agent() as guide_agent,
    ):
        game_play_prompt = await game_mcp.get_prompt("game_play_prompt")
        agent42_tool = build_agent42_tool(agent42)
        guide_tool = build_city_guide_tool(guide_agent)

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

The game MCP connection and Agent42 both send the same
`Authorization: Bearer` credential. The key stays in **.env** and in HTTP
headers; it is not added as a model instruction or tool argument.

Run the complete player:

```powershell
python agent.py
```

Expected flow:

1. The MCP server recognizes the nickname registered on this page.
2. The agent starts or resumes the authenticated quest.
3. It calls **ask_agent42** for movement missions.
4. Agent42 advice appears on this Player timeline.
5. It calls **ask_city_guide** for guide questions.
6. Completed missions and the final result appear on the timeline.

> **Checkpoint:** the terminal shows the final game result, the session log
> contains calls to the game MCP tools, **ask_agent42**, and
> **ask_city_guide**, and this page shows the same journey without exposing the
> private key.

## What You Learned

You composed MCP and A2A specialists into one authenticated player agent. One
browser-issued key now connects game actions, Agent42 advice, and the visual
Player timeline.
