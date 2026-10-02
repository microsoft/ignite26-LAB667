"""Offline regressions for the runnable player and current framework APIs."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agent_framework import (
    Agent,
    AgentResponse,
    AgentSession,
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationContext,
    FunctionInvocationLayer,
    Message,
    SessionContext,
)

PLAYER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLAYER_DIR))

import agent as player
import agent_agent42 as transport
import agent_city_guide as guide
import log as session_log


ENV = {
    "PYTHON_DOTENV_DISABLED": "1",
    "AZURE_OPENAI_ENDPOINT": "https://model.invalid",
    "AZURE_OPENAI_API_KEY": "offline-key",
    "AZURE_OPENAI_DEPLOYMENT_NAME": "main-model",
    "AZURE_SEARCH_ENDPOINT": "https://search.invalid",
    "AZURE_SEARCH_KEY": "offline-search-key",
    "AZURE_SEARCH_KNOWLEDGE_BASE_NAME": "city-knowledgebase",
    "GAME_MCP_URL": "http://game.invalid/city/mcp",
    "AGENT42_URL": "http://agent42.invalid",
}


def managed_resource() -> MagicMock:
    resource = MagicMock()
    resource.__aenter__ = AsyncMock(return_value=resource)
    resource.__aexit__ = AsyncMock(return_value=False)
    return resource


class OfflineChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    def __init__(self) -> None:
        super().__init__()
        self.seen_messages: list[Message] = []
        self.seen_options: dict[str, Any] = {}

    async def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> ChatResponse:
        if stream:
            raise NotImplementedError("This offline fixture only supports non-streaming replies.")
        self.seen_messages = list(messages)
        self.seen_options = dict(options)
        return ChatResponse(messages=[Message("assistant", ["Offline ready"])])


class PlayerMainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, ENV, clear=True))
        self.enterContext(patch("builtins.print"))
        self.client = MagicMock()
        self.client.client = managed_resource()
        self.mcp = managed_resource()
        self.mcp.get_prompt = AsyncMock(return_value="Game instructions from MCP")
        self.agent42 = managed_resource()
        self.guide = managed_resource()
        self.agent = MagicMock(spec=Agent)
        self.agent.create_session.return_value = AgentSession()
        self.agent.run = AsyncMock(
            return_value=AgentResponse(messages=[Message("assistant", ["Ready"])])
        )
        self.constructor = self.enterContext(patch.object(player, "Agent", return_value=self.agent))
        self.enterContext(patch.object(player, "OpenAIChatClient", return_value=self.client))
        self.mcp_constructor = self.enterContext(
            patch.object(player, "MCPStreamableHTTPTool", return_value=self.mcp)
        )
        self.enterContext(patch.object(player, "build_agent42_agent", return_value=self.agent42))
        self.enterContext(patch.object(player, "build_city_guide_agent", return_value=self.guide))
        self.agent42_tool = self.enterContext(patch.object(player, "build_agent42_tool"))
        self.guide_tool = self.enterContext(patch.object(player, "build_city_guide_tool"))
        self.enterContext(
            patch.object(player, "open_session_log", return_value=Path(self.temp) / "session.log")
        )
        self.input = self.enterContext(patch("builtins.input", return_value="quit"))

    def assert_closed(self) -> None:
        for resource in (self.client.client, self.mcp, self.agent42, self.guide):
            resource.__aexit__.assert_awaited_once()

    async def test_main_preserves_prompt_tools_session_and_chat_loop(self) -> None:
        self.input.side_effect = ["", "look around", "QUIT"]
        await player.main()
        self.mcp_constructor.assert_called_once_with(
            name="Gaming MCP Server", url=ENV["GAME_MCP_URL"]
        )
        self.mcp.get_prompt.assert_awaited_once_with("game_play_prompt")
        self.agent42_tool.assert_called_once_with(self.agent42)
        self.guide_tool.assert_called_once_with(self.guide)
        options = self.constructor.call_args.kwargs
        self.assertEqual(options["instructions"], "Game instructions from MCP")
        self.assertEqual(options["tools"], [
            self.mcp, player.save_player_id, self.agent42_tool.return_value,
            self.guide_tool.return_value,
        ])
        self.assertEqual(len(options["context_providers"]), 1)
        self.assertEqual(len(options["middleware"]), 3)
        self.assertEqual([call.args[0] for call in self.agent.run.await_args_list],
                         ["start the game", "look around"])
        for call in self.agent.run.await_args_list:
            self.assertIs(call.kwargs["session"], self.agent.create_session.return_value)
        self.assert_closed()

    async def test_prompt_failure_closes_all_connections(self) -> None:
        self.mcp.get_prompt.side_effect = RuntimeError("prompt unavailable")
        with self.assertRaisesRegex(RuntimeError, "prompt unavailable"):
            await player.main()
        self.agent.run.assert_not_awaited()
        self.assert_closed()

    async def test_model_failure_closes_all_connections(self) -> None:
        self.agent.run.side_effect = RuntimeError("model unavailable")
        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            await player.main()
        self.assert_closed()

    async def test_cancellation_closes_all_connections(self) -> None:
        self.agent.run.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await player.main()
        self.assert_closed()

    async def test_early_specialist_failure_closes_entered_connections(self) -> None:
        self.guide.__aenter__.side_effect = RuntimeError("search configuration invalid")
        with self.assertRaisesRegex(RuntimeError, "search configuration invalid"):
            await player.main()
        for resource in (self.client.client, self.mcp, self.agent42):
            resource.__aexit__.assert_awaited_once()
        self.guide.__aexit__.assert_not_awaited()

    async def test_eof_and_keyboard_interrupt_close_connections(self) -> None:
        for exception in (EOFError, KeyboardInterrupt):
            with self.subTest(exception=exception):
                self.input.side_effect = exception
                await player.main()
                self.assert_closed()
                for resource in (self.client.client, self.mcp, self.agent42, self.guide):
                    resource.__aexit__.reset_mock()


class MemoryAndMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = Path(self.enterContext(TemporaryDirectory()))
        self.memory = self.temp / "memory.json"
        self.source_memory = player.MEMORY_FILE
        self.enterContext(patch.object(player, "MEMORY_FILE", self.memory))
        self.provider = player.PlayerContextProvider(source_id="player-memory")

    async def apply_memory(self) -> SessionContext:
        context = SessionContext(input_messages=[Message("user", ["hello"])])
        await self.provider.before_run(
            agent=MagicMock(spec=Agent), session=AgentSession(), context=context, state={}
        )
        return context

    async def test_memory_round_trip_with_real_agent_and_logging(self) -> None:
        await player.save_player_id.invoke(player_id="player-42")
        self.assertEqual(json.loads(self.memory.read_text(encoding="utf-8")),
                         {"player_id": "player-42"})
        client = OfflineChatClient()
        log_path = self.temp / "session.log"
        middleware = session_log.build_logging_middleware(log_path)
        agent = Agent(client=client, context_providers=[self.provider], middleware=list(middleware))
        response = await agent.run("hello")
        self.assertEqual(response.text, "Offline ready")
        self.assertEqual(client.seen_options["instructions"],
                         "From memory: player_id: player-42")
        log_text = log_path.read_text(encoding="utf-8")
        for text in ("USER ->", "MODEL INPUT", "player-42", "AGENT <-", "Offline ready"):
            self.assertIn(text, log_text)

    async def test_missing_and_empty_memory_do_not_invent_identity(self) -> None:
        self.assertFalse((await self.apply_memory()).instructions)
        self.memory.write_text("{}", encoding="utf-8")
        self.assertFalse((await self.apply_memory()).instructions)

    async def test_invalid_memory_is_reported(self) -> None:
        for text in ("not-json", "[]", '{"player_id": 42}', '{"player_id": ""}'):
            with self.subTest(text=text):
                self.memory.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    await self.apply_memory()

    async def test_blank_player_id_does_not_overwrite_memory(self) -> None:
        self.memory.write_text('{"player_id": "existing"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            await player.save_player_id.invoke(player_id=" ")
        self.assertEqual(json.loads(self.memory.read_text(encoding="utf-8")),
                         {"player_id": "existing"})

    async def test_function_log_serializes_current_content_results(self) -> None:
        log_path = self.temp / "tools.log"
        function_middleware = session_log.build_logging_middleware(log_path)[2]
        context = FunctionInvocationContext(
            function=player.save_player_id, arguments={"player_id": "player-42"}
        )

        async def call_next() -> None:
            context.result = [Content.from_text("Route reply")]

        await function_middleware(context, call_next)
        text = log_path.read_text(encoding="utf-8")
        self.assertIn("TOOL CALL  save_player_id", text)
        self.assertIn('"player_id": "player-42"', text)
        self.assertIn("TOOL RESULT save_player_id", text)
        self.assertIn('"text": "Route reply"', text)
        self.assertNotIn("object at", text)

    def test_memory_path_does_not_depend_on_working_directory(self) -> None:
        source_memory = PLAYER_DIR / "memory.json"
        self.assertEqual(self.source_memory, source_memory)


class SpecialistTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, ENV, clear=True))
        self.client = MagicMock()
        self.client.client = managed_resource()
        self.client_factory = self.enterContext(
            patch.object(guide, "OpenAIChatClient", return_value=self.client)
        )
        self.search = managed_resource()
        self.search_factory = self.enterContext(
            patch.object(guide, "AzureAISearchContextProvider", return_value=self.search)
        )
        self.guide = MagicMock(spec=Agent)
        self.guide.run = AsyncMock(return_value=AgentResponse())
        self.agent_factory = self.enterContext(patch.object(guide, "Agent", return_value=self.guide))

    async def test_city_guide_default_and_blank_overrides_reuse_main_configuration(self) -> None:
        for overrides in ({}, {
            "CITY_GUIDE_AZURE_OPENAI_ENDPOINT": "",
            "CITY_GUIDE_AZURE_OPENAI_API_KEY": " ",
            "CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME": "",
        }):
            with self.subTest(overrides=overrides), patch.dict(os.environ, overrides):
                async with guide.build_city_guide_agent() as agent:
                    self.assertIs(agent, self.guide)
                    guide.build_city_guide_tool(agent)
                self.client_factory.assert_called_with(
                    azure_endpoint=ENV["AZURE_OPENAI_ENDPOINT"],
                    api_key=ENV["AZURE_OPENAI_API_KEY"],
                    model=ENV["AZURE_OPENAI_DEPLOYMENT_NAME"],
                )
                self.search_factory.assert_called_with(
                    endpoint=ENV["AZURE_SEARCH_ENDPOINT"],
                    knowledge_base_name=ENV["AZURE_SEARCH_KNOWLEDGE_BASE_NAME"],
                    api_key=ENV["AZURE_SEARCH_KEY"],
                    mode="agentic",
                )
                self.assertEqual(self.agent_factory.call_args.kwargs["context_providers"],
                                 [self.search])
        self.assertEqual(self.client.client.__aexit__.await_count, 2)
        self.assertEqual(self.search.__aexit__.await_count, 2)

    async def test_city_guide_honors_explicit_resource_and_model(self) -> None:
        with patch.dict(os.environ, {
            "CITY_GUIDE_AZURE_OPENAI_ENDPOINT": "https://guide.invalid",
            "CITY_GUIDE_AZURE_OPENAI_API_KEY": "guide-key",
            "CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME": "guide-model",
        }):
            async with guide.build_city_guide_agent():
                self.client_factory.assert_called_once_with(
                    azure_endpoint="https://guide.invalid", api_key="guide-key", model="guide-model"
                )

    async def test_city_guide_closes_model_client_if_search_setup_fails(self) -> None:
        self.search_factory.side_effect = RuntimeError("bad search setup")
        with self.assertRaisesRegex(RuntimeError, "bad search setup"):
            async with guide.build_city_guide_agent():
                self.fail("The provider should not start.")
        self.client.client.__aexit__.assert_awaited_once()

    async def test_city_guide_smoke_failure_closes_search_and_model(self) -> None:
        self.guide.run.side_effect = RuntimeError("search unavailable")
        with self.assertRaisesRegex(RuntimeError, "search unavailable"):
            await guide.main()
        self.search.__aexit__.assert_awaited_once()
        self.client.client.__aexit__.assert_awaited_once()

    async def test_agent42_smoke_failure_closes_a2a_client(self) -> None:
        remote = managed_resource()
        remote.run = AsyncMock(side_effect=RuntimeError("agent42 unavailable"))
        with patch.object(transport, "build_agent42_agent", return_value=remote):
            with self.assertRaisesRegex(RuntimeError, "agent42 unavailable"):
                await transport.main()
        remote.__aexit__.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
