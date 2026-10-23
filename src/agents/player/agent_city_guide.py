"""City guide specialist agent for San Francisco knowledge-base questions."""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from agent_framework import Agent, FunctionTool, MCPStreamableHTTPTool
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv


@asynccontextmanager
async def build_city_guide_agent() -> AsyncGenerator[Agent, None]:
	client = OpenAIChatClient(
		azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
		api_key=os.environ["AZURE_OPENAI_API_KEY"],
		model=(
			os.environ.get("CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME", "").strip()
			or os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]
		),
	)

	# Every Foundry IQ knowledge base is also an MCP server with one tool:
	# knowledge_base_retrieve.
	search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"].rstrip("/")
	knowledge_base = os.environ["AZURE_SEARCH_KNOWLEDGE_BASE_NAME"]
	city_guide_kb = MCPStreamableHTTPTool(
		name="City Guide Knowledge Base",
		url=f"{search_endpoint}/knowledgebases/{knowledge_base}/mcp?api-version=2026-08-01-preview",
		static_headers={"api-key": os.environ["AZURE_SEARCH_KEY"]},
	)

	async with client.client, city_guide_kb:
		yield Agent(
			client=client,
			name="San Francisco City Guide Agent",
			instructions=(
				"Answer San Francisco city guide questions. Always search the city guide "
				"knowledge base first and answer only from what it returns. "
				"Keep answers brief and return only the answer the game needs."
			),
			tools=[city_guide_kb],
		)


def build_city_guide_tool(guide_agent: Agent) -> FunctionTool:
	# The main game agent calls this tool only for city guide questions.
	return guide_agent.as_tool(
		name="ask_city_guide",
		description=(
			"Ask the San Francisco city guide a question. Use this only "
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
