"""Game play agent using Microsoft Agent Framework with Azure OpenAI."""

import asyncio
import json
import logging
import os
from pathlib import Path

from agent_framework import Agent, ContextProvider, MCPStreamableHTTPTool, tool
from agent_framework.openai import OpenAIChatClient
from agent_framework_foundry import FoundryChatClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

from agent_agent42 import build_agent42_tool
from agent_city_guide import build_city_guide_tool
from log import build_logging_middleware, open_session_log

#logging.basicConfig(level=logging.INFO)
#logging.getLogger("agent_framework.azure_ai_search").setLevel(logging.DEBUG)


load_dotenv(override=True)

MEMORY_FILE = Path("memory.json")

# ANSI color codes for terminal output.
GREEN = "\033[32m"
PURPLE = "\033[35m"
RESET = "\033[0m"

async def main() -> None:

    # Step 1 - Create the chat client the main game agent uses to reason and choose tools.
    client = OpenAIChatClient(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    )

    # Step 2 - Start a session log so workshop participants can inspect each model/tool call.
    log_path = open_session_log()
    print(f"Session log: {log_path}")
    agent_mw, chat_mw, function_mw = build_logging_middleware(log_path)

    # Step 3 - Memory: remember the player_id between runs.
    class PlayerContextProvider(ContextProvider):
        async def before_run(self, *, agent, session, context, state) -> None:
            if MEMORY_FILE.exists():
                pid = json.loads(MEMORY_FILE.read_text()).get("player_id")
                if pid:
                    context.extend_instructions(self.source_id, f"From memory: player_id: {pid}")

    @tool(description="Save the player_id returned after registration")
    async def save_player_id(player_id: str) -> str:
        MEMORY_FILE.write_text(json.dumps({"player_id": player_id}))
        return f"Player ID {player_id} saved."

    # Step 4 - Connect to the game server. This gives the agent tools like start, move, and submit answer.
    game_mcp = MCPStreamableHTTPTool(
        name="Gaming MCP Server",
        url=os.environ["GAME_MCP_URL"],
    )
    await game_mcp.connect()
    game_play_prompt = await game_mcp.get_prompt("game_play_prompt")

    # Step 5 - Connect to Agent42, the A2A-enabled local transport expert.
    agent42_tool = build_agent42_tool()

    # Step 6 - Add the city guide specialist. Its Azure Search context runs only when this tool is called.
    guide_tool, city_guide_search = build_city_guide_tool()

    # The main agent orchestrates the game and delegates specialist work to Agent42 and the city guide agent.
    agent = Agent(
        client=client,
        name="Game Play Agent",
        instructions=game_play_prompt,
        tools=[game_mcp, save_player_id, agent42_tool, guide_tool],
        context_providers=[
            PlayerContextProvider(source_id="player-memory"),
        ],
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

    await game_mcp.close()
    await city_guide_search.close()


if __name__ == "__main__":
    asyncio.run(main())
