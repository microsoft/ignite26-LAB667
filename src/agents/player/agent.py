"""Game play agent using Microsoft Agent Framework with Azure OpenAI."""

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

from agent_agent42 import build_agent42_agent, build_agent42_tool
from agent_city_guide import build_city_guide_agent, build_city_guide_tool
from log import build_logging_middleware, open_session_log

MEMORY_FILE = Path(__file__).resolve().with_name("memory.json")

# ANSI color codes for terminal output.
GREEN = "\033[32m"
PURPLE = "\033[35m"
RESET = "\033[0m"


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

    # Step 1 - Create the chat client the main game agent uses to reason and choose tools.
    client = OpenAIChatClient(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    )

    async with client.client:
        log_path = open_session_log()
        print(f"Session log: {log_path}")
        agent_mw, chat_mw, function_mw = build_logging_middleware(log_path)

        # Context managers close connections on normal exit, cancellation, and failures.
        async with (
            MCPStreamableHTTPTool(
                name="Gaming MCP Server",
                url=os.environ["GAME_MCP_URL"],
            ) as game_mcp,
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
                tools=[game_mcp, save_player_id, agent42_tool, guide_tool],
                context_providers=[PlayerContextProvider(source_id="player-memory")],
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
