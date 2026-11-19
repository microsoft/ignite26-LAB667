"""Direct MCP connection to the San Francisco city guide knowledge base."""

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Generator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv
from httpx2 import AsyncClient, Timeout
from mcp import Client, types
from mcp.client.streamable_http import streamable_http_client


class CityGuideClient(Client):
	async def send_ping(self, *, meta: types.RequestParamsMeta | None = None) -> types.EmptyResult:
		# This client uses the legacy protocol, where session pings remain supported.
		return await self.session.send_ping(meta=meta)

	async def list_tools(self, **kwargs: Any) -> types.ListToolsResult:
		result = await super().list_tools(**kwargs)
		tools = []
		for tool in result.tools:
			# AF 1.23 skips optional Tasks even though ordinary calls remain supported.
			if (
				tool.name == "knowledge_base_retrieve"
				and tool.execution is not None
				and tool.execution.task_support == "optional"
			):
				tool = tool.model_copy(update={"execution": None})
			tools.append(tool)
		return result.model_copy(update={"tools": tools})


@contextmanager
def configured_legacy_notifications() -> Generator[None, None, None]:
	"""Hide only AF 1.23's inaccurate setup warning after wiring its handler."""
	scope = ContextVar("city_guide_legacy_setup", default=False)
	token = scope.set(True)
	logger = logging.getLogger("agent_framework._mcp")

	def keep_record(record: logging.LogRecord) -> bool:
		return not (
			scope.get()
			and record.levelno == logging.WARNING
			and record.getMessage() == (
				"Automatic legacy catalog refresh is unavailable for a caller-owned Client; "
				"configure legacy notification handling when constructing the Client."
			)
		)

	logger.addFilter(keep_record)
	try:
		yield
	finally:
		logger.removeFilter(keep_record)
		scope.reset(token)


def build_city_guide_tool() -> AbstractAsyncContextManager[MCPStreamableHTTPTool]:
	search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"].rstrip("/")
	knowledge_base = os.environ["AZURE_SEARCH_KNOWLEDGE_BASE_NAME"]
	search_key = os.environ["AZURE_SEARCH_KEY"]
	url = f"{search_endpoint}/knowledgebases/{knowledge_base}/mcp?api-version=2026-08-01-preview"

	@asynccontextmanager
	async def connect() -> AsyncGenerator[MCPStreamableHTTPTool, None]:
		async with AsyncClient(
			headers={"api-key": search_key},
			timeout=Timeout(60.0, read=300.0),
			follow_redirects=False,
		) as http_client:
			transport = streamable_http_client(url, http_client=http_client)
			mcp_client = CityGuideClient(transport, mode="legacy")
			city_guide = MCPStreamableHTTPTool(
				name="City Guide Knowledge Base",
				mcp_client=mcp_client,
				allowed_tools=["knowledge_base_retrieve"],
				load_prompts=False,
			)
			mcp_client.message_handler = city_guide.message_handler
			async with mcp_client, AsyncExitStack() as stack:
				with configured_legacy_notifications():
					await stack.enter_async_context(city_guide)
				if not any(tool.name == "knowledge_base_retrieve" for tool in city_guide.functions):
					raise RuntimeError(
						"The knowledge base did not expose knowledge_base_retrieve. "
						"Check Search permissions and tool metadata; required MCP Tasks are not supported."
					)
				yield city_guide

	return connect()


async def main() -> None:
	load_dotenv(Path(__file__).with_name(".env"), override=True)

	client = OpenAIChatClient(
		azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/").removesuffix("/openai/v1"),
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
