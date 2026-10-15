"""Agent42 transport specialist tool for movement missions."""

import asyncio
import os
from pathlib import Path

import httpx
from agent_framework import FunctionTool
from agent_framework.a2a import A2AAgent
from dotenv import load_dotenv


def build_agent42_agent() -> A2AAgent:
    # Agent42 is a deployed A2A agent. The URL comes from .env.
    timeout = httpx.Timeout(
        float(os.getenv("AGENT42_TIMEOUT_SECONDS", "60")),
        connect=10.0,
    )
    client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {os.environ['GAME_API_KEY']}"},
        timeout=timeout,
    )
    return A2AAgent(
        name="Agent42",
        description=(
            "Local transport expert. Given an origin and destination, recommends "
            "car/taxi vs walking vs bike using live weather and real-time traffic, "
            "and returns a static map of the chosen route plus a recommendation code."
        ),
        url=os.environ["AGENT42_URL"],
        http_client=client,
    )


def build_agent42_tool(agent42: A2AAgent) -> FunctionTool:
    # The main game agent calls this tool for movement quests.
    return agent42.as_tool(
        name="ask_agent42",
        description=(
            "Ask Agent42 for the best way to get from one place to another. "
            "Pass a full natural-language question including origin, destination."
        ),
        arg_name="question",
        arg_description="The transport question to send to Agent42.",
    )


async def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"), override=True)

    question = "What is the best way to get from the Ferry Building to Golden Gate Park?"
    async with build_agent42_agent() as agent42:
        response = await agent42.run(question)
        print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
