"""Direct MCP connection to the San Francisco city guide knowledge base."""

import asyncio
import os
from pathlib import Path

from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv


def build_city_guide_tool() -> MCPStreamableHTTPTool:
	search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"].rstrip("/")
	knowledge_base = os.environ["AZURE_SEARCH_KNOWLEDGE_BASE_NAME"]
	return MCPStreamableHTTPTool(
		name="City Guide Knowledge Base",
		url=f"{search_endpoint}/knowledgebases/{knowledge_base}/mcp?api-version=2026-08-01-preview",
		static_headers={"api-key": os.environ["AZURE_SEARCH_KEY"]},
		allowed_tools=["knowledge_base_retrieve"],
		load_prompts=False,
	)


async def main() -> None:
	load_dotenv(Path(__file__).with_name(".env"), override=True)

	client = OpenAIChatClient(
		azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
		api_key=os.environ["AZURE_OPENAI_API_KEY"],
		model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
	)

	async with client.client, build_city_guide_tool() as city_guide:
		if not any(tool.name == "knowledge_base_retrieve" for tool in city_guide.functions):
			raise RuntimeError("The knowledge base did not expose knowledge_base_retrieve.")
		test_agent = Agent(
			client=client,
			name="City Guide Test Agent",
			instructions=(
				"Always call knowledge_base_retrieve to answer the question. "
				"Answer only from the knowledge base result, not from memory. "
				"Keep the answer brief."
			),
			tools=[city_guide],
		)
		response = await test_agent.run("What neighborhood is Dolores Park in?")
		print(response.text)


if __name__ == "__main__":
	asyncio.run(main())
