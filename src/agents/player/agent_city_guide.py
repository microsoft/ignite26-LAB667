"""City guide specialist agent for San Francisco knowledge-base questions."""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from agent_framework import Agent, FunctionTool
from agent_framework.azure import AzureAISearchContextProvider
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv


@asynccontextmanager
async def build_city_guide_agent() -> AsyncGenerator[Agent, None]:
    client = OpenAIChatClient(
        azure_endpoint=(
            os.environ.get("CITY_GUIDE_AZURE_OPENAI_ENDPOINT", "").strip()
            or os.environ["AZURE_OPENAI_ENDPOINT"]
        ),
        api_key=(
            os.environ.get("CITY_GUIDE_AZURE_OPENAI_API_KEY", "").strip()
            or os.environ["AZURE_OPENAI_API_KEY"]
        ),
        model=(
            os.environ.get("CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME", "").strip()
            or os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]
        ),
    )

    # Search context belongs here, so the main game agent does not spend RAG tokens on every turn.
    async with client.client:
        async with AzureAISearchContextProvider(
            endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
            knowledge_base_name=os.environ["AZURE_SEARCH_KNOWLEDGE_BASE_NAME"],
            api_key=os.environ["AZURE_SEARCH_KEY"],
            mode="agentic",
        ) as search_context_provider:
            yield Agent(
                client=client,
                name="San Francisco City Guide Agent",
                instructions=(
                    "Answer San Francisco city guide questions using the provided search context. "
                    "Keep answers brief and return only the answer needed by the game."
                ),
                context_providers=[search_context_provider],
            )


def build_city_guide_tool(guide_agent: Agent) -> FunctionTool:
    # The main game agent calls this tool only for city guide questions.
    return guide_agent.as_tool(
        name="ask_city_guide",
        description=(
            "Ask the San Francisco city guide knowledge base a question. Use this only "
            "for city guide or local knowledge questions from the game."
        ),
        arg_name="question",
        arg_description="The city guide question to answer.",
    )


async def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"), override=True)

    question = "What neighborhood is Dolores Park in?"

    async with build_city_guide_agent() as guide_agent:
        response = await guide_agent.run(question)
        print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
