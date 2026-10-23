"""Offline regressions for the runnable player and current framework APIs."""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from agent_framework import (
    Agent,
    AgentResponse,
    AgentSession,
    Message,
)

PLAYER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLAYER_DIR))

import agent as player
import agent_agent42 as transport
import agent_city_guide as guide


ENV = {
    "PYTHON_DOTENV_DISABLED": "1",
    "AZURE_OPENAI_ENDPOINT": "https://model.invalid",
    "AZURE_OPENAI_API_KEY": "offline-key",
    "AZURE_OPENAI_DEPLOYMENT_NAME": "main-model",
    "AZURE_SEARCH_ENDPOINT": "https://search.invalid",
    "AZURE_SEARCH_KEY": "offline-search-key",
    "AZURE_SEARCH_KNOWLEDGE_BASE_NAME": "san-francisco-cityguide",
    "GAME_MCP_URL": "http://game.invalid/city/mcp",
    "GAME_API_KEY": "litc.city.offline-player-key",
    "AGENT42_URL": "http://agent42.invalid",
}


def managed_resource() -> MagicMock:
    resource = MagicMock()
    resource.__aenter__ = AsyncMock(return_value=resource)
    resource.__aexit__ = AsyncMock(return_value=False)
    return resource


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
            name="Gaming MCP Server",
            url=ENV["GAME_MCP_URL"],
            static_headers={"Authorization": f"Bearer {ENV['GAME_API_KEY']}"},
        )
        self.mcp.get_prompt.assert_awaited_once_with("game_play_prompt")
        self.agent42_tool.assert_called_once_with(self.agent42)
        self.guide_tool.assert_called_once_with(self.guide)
        options = self.constructor.call_args.kwargs
        self.assertEqual(options["instructions"], "Game instructions from MCP")
        self.assertEqual(options["tools"], [
            self.mcp, self.agent42_tool.return_value, self.guide_tool.return_value,
        ])
        self.assertNotIn("context_providers", options)
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


class SpecialistTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, ENV, clear=True))
        self.client = MagicMock()
        self.client.client = managed_resource()
        self.client_factory = self.enterContext(
            patch.object(guide, "OpenAIChatClient", return_value=self.client)
        )
        self.kb = managed_resource()
        self.kb_factory = self.enterContext(
            patch.object(guide, "MCPStreamableHTTPTool", return_value=self.kb)
        )
        self.guide = MagicMock(spec=Agent)
        self.guide.run = AsyncMock(return_value=AgentResponse())
        self.agent_factory = self.enterContext(patch.object(guide, "Agent", return_value=self.guide))

    async def test_city_guide_uses_knowledge_base_mcp_and_main_model_by_default(self) -> None:
        for overrides in ({}, {"CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME": " "}):
            with self.subTest(overrides=overrides), patch.dict(os.environ, overrides):
                async with guide.build_city_guide_agent() as agent:
                    self.assertIs(agent, self.guide)
                    guide.build_city_guide_tool(agent)
                self.client_factory.assert_called_with(
                    azure_endpoint=ENV["AZURE_OPENAI_ENDPOINT"],
                    api_key=ENV["AZURE_OPENAI_API_KEY"],
                    model=ENV["AZURE_OPENAI_DEPLOYMENT_NAME"],
                )
                self.kb_factory.assert_called_with(
                    name="City Guide Knowledge Base",
                    url=(
                        "https://search.invalid/knowledgebases/san-francisco-cityguide/mcp"
                        "?api-version=2026-08-01-preview"
                    ),
                    static_headers={"api-key": ENV["AZURE_SEARCH_KEY"]},
                )
                self.assertEqual(self.agent_factory.call_args.kwargs["tools"], [self.kb])
        self.assertEqual(self.client.client.__aexit__.await_count, 2)
        self.assertEqual(self.kb.__aexit__.await_count, 2)

    async def test_city_guide_honors_model_override(self) -> None:
        with patch.dict(os.environ, {"CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME": "guide-model"}):
            async with guide.build_city_guide_agent():
                self.assertEqual(self.client_factory.call_args.kwargs["model"], "guide-model")

    async def test_city_guide_closes_model_client_if_knowledge_base_fails(self) -> None:
        self.kb.__aenter__.side_effect = RuntimeError("bad knowledge base")
        with self.assertRaisesRegex(RuntimeError, "bad knowledge base"):
            async with guide.build_city_guide_agent():
                self.fail("The agent should not start.")
        self.client.client.__aexit__.assert_awaited_once()

    async def test_city_guide_smoke_failure_closes_knowledge_base_and_model(self) -> None:
        self.guide.run.side_effect = RuntimeError("search unavailable")
        with self.assertRaisesRegex(RuntimeError, "search unavailable"):
            await guide.main()
        self.kb.__aexit__.assert_awaited_once()
        self.client.client.__aexit__.assert_awaited_once()

    async def test_agent42_smoke_failure_closes_a2a_client(self) -> None:
        remote = managed_resource()
        remote.run = AsyncMock(side_effect=RuntimeError("agent42 unavailable"))
        with patch.object(transport, "build_agent42_agent", return_value=remote):
            with self.assertRaisesRegex(RuntimeError, "agent42 unavailable"):
                await transport.main()
        remote.__aexit__.assert_awaited_once()

    def test_agent42_client_allows_transport_workflow_to_complete(self) -> None:
        http_client = MagicMock()
        with (
            patch.object(transport.httpx, "AsyncClient", return_value=http_client) as client_factory,
            patch.object(transport, "A2AAgent") as agent_factory,
        ):
            transport.build_agent42_agent()

        timeout = client_factory.call_args.kwargs["timeout"]
        self.assertEqual(timeout.connect, 10.0)
        self.assertEqual(timeout.read, 60.0)
        agent_factory.assert_called_once_with(
            name="Agent42",
            description=unittest.mock.ANY,
            url=ENV["AGENT42_URL"],
            http_client=http_client,
        )


if __name__ == "__main__":
    unittest.main()
