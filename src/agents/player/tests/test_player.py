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
import agent_note_reader as note_reader


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
        self.note_reader = managed_resource()
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
        self.agent42_tool = self.enterContext(patch.object(player, "build_agent42_tool"))
        self.guide_tool = self.enterContext(
            patch.object(player, "build_city_guide_tool", return_value=self.guide)
        )
        self.enterContext(
            patch.object(player, "build_note_reader_agent", return_value=self.note_reader)
        )
        self.note_tool = self.enterContext(patch.object(player, "build_note_reader_tool"))
        self.enterContext(
            patch.object(player, "open_session_log", return_value=Path(self.temp) / "session.log")
        )
        self.input = self.enterContext(patch("builtins.input", return_value="quit"))

    def assert_closed(self) -> None:
        for resource in (self.client.client, self.mcp, self.agent42, self.guide, self.note_reader):
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
        self.guide_tool.assert_called_once_with()
        self.note_tool.assert_called_once_with(self.note_reader)
        options = self.constructor.call_args.kwargs
        self.assertEqual(options["instructions"], "Game instructions from MCP")
        self.assertEqual(options["tools"], [
            self.mcp, self.agent42_tool.return_value, self.guide, self.note_tool.return_value,
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
        self.note_reader.__aenter__.assert_not_awaited()

    async def test_eof_and_keyboard_interrupt_close_connections(self) -> None:
        for exception in (EOFError, KeyboardInterrupt):
            with self.subTest(exception=exception):
                self.input.side_effect = exception
                await player.main()
                self.assert_closed()
                for resource in (self.client.client, self.mcp, self.agent42, self.guide, self.note_reader):
                    resource.__aexit__.reset_mock()


class SpecialistTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, ENV, clear=True))
        self.kb = managed_resource()
        retrieval_tool = MagicMock()
        retrieval_tool.name = "knowledge_base_retrieve"
        self.kb.functions = [retrieval_tool]
        self.kb_factory = self.enterContext(
            patch.object(guide, "MCPStreamableHTTPTool", return_value=self.kb)
        )
        self.http = managed_resource()
        self.http_factory = self.enterContext(patch.object(guide, "AsyncClient", return_value=self.http))
        self.mcp_client = managed_resource()
        self.mcp_client_factory = self.enterContext(
            patch.object(guide, "CityGuideClient", return_value=self.mcp_client)
        )
        self.transport_factory = self.enterContext(patch.object(guide, "streamable_http_client"))
        self.client = MagicMock()
        self.client.client = managed_resource()
        self.client_factory = self.enterContext(
            patch.object(guide, "OpenAIChatClient", return_value=self.client)
        )
        self.test_agent = MagicMock(spec=Agent)
        self.test_agent.run = AsyncMock(
            return_value=AgentResponse(
                messages=[Message("assistant", ["Dolores Park is in the Mission District."])]
            )
        )
        self.agent_factory = self.enterContext(
            patch.object(guide, "Agent", return_value=self.test_agent)
        )

    async def test_city_guide_returns_mcp_tool_without_model_configuration(self) -> None:
        search_env = {key: value for key, value in ENV.items() if key.startswith("AZURE_SEARCH_")}
        for endpoint in ("https://search.invalid", "https://search.invalid/"):
            with (
                self.subTest(endpoint=endpoint),
                patch.dict(os.environ, {**search_env, "AZURE_SEARCH_ENDPOINT": endpoint}, clear=True),
            ):
                async with guide.build_city_guide_tool() as kb:
                    self.assertIs(kb, self.kb)
                self.kb_factory.assert_called_with(
                    name="City Guide Knowledge Base",
                    mcp_client=self.mcp_client,
                    allowed_tools=["knowledge_base_retrieve"],
                    load_prompts=False,
                )
                self.transport_factory.assert_called_with(
                    "https://search.invalid/knowledgebases/san-francisco-cityguide/mcp"
                    "?api-version=2026-08-01-preview",
                    http_client=self.http,
                )
                self.assertEqual(self.http_factory.call_args.kwargs["headers"], {"api-key": ENV["AZURE_SEARCH_KEY"]})
                self.assertFalse(self.http_factory.call_args.kwargs["follow_redirects"])
        self.assertEqual(self.http.__aexit__.await_count, 2)
        self.assertEqual(self.mcp_client.__aexit__.await_count, 2)
        self.client_factory.assert_not_called()
        self.agent_factory.assert_not_called()

    def test_city_guide_requires_search_key(self) -> None:
        del os.environ["AZURE_SEARCH_KEY"]
        with self.assertRaisesRegex(KeyError, "AZURE_SEARCH_KEY"):
            guide.build_city_guide_tool()
        self.kb_factory.assert_not_called()

    async def test_city_guide_standalone_agent_asks_question_and_closes(self) -> None:
        with patch("builtins.print") as output:
            await guide.main()
        self.client_factory.assert_called_once_with(
            azure_endpoint=ENV["AZURE_OPENAI_ENDPOINT"],
            api_key=ENV["AZURE_OPENAI_API_KEY"],
            model=ENV["AZURE_OPENAI_DEPLOYMENT_NAME"],
        )
        options = self.agent_factory.call_args.kwargs
        self.assertIs(options["client"], self.client)
        self.assertEqual(options["tools"], [self.kb])
        self.assertIn("Always call knowledge_base_retrieve", options["instructions"])
        self.assertIn("not from memory", options["instructions"])
        self.test_agent.run.assert_awaited_once_with("What neighborhood is Dolores Park in?")
        output.assert_called_once_with("Dolores Park is in the Mission District.")
        self.kb.__aenter__.assert_awaited_once()
        self.kb.__aexit__.assert_awaited_once()
        self.http.__aexit__.assert_awaited_once()
        self.mcp_client.__aexit__.assert_awaited_once()
        self.client.client.__aexit__.assert_awaited_once()

    async def test_city_guide_connection_check_rejects_missing_tool_and_closes(self) -> None:
        self.kb.functions = []
        with (
            patch("builtins.print") as output,
            self.assertRaisesRegex(RuntimeError, "did not expose knowledge_base_retrieve"),
        ):
            await guide.main()
        output.assert_not_called()
        self.agent_factory.assert_not_called()
        self.kb.__aexit__.assert_awaited_once()
        self.client.client.__aexit__.assert_awaited_once()

    async def test_city_guide_connection_failure_propagates(self) -> None:
        self.kb.__aenter__.side_effect = RuntimeError("search unavailable")
        with self.assertRaisesRegex(RuntimeError, "search unavailable"):
            await guide.main()
        self.kb.__aexit__.assert_not_awaited()
        self.client.client.__aexit__.assert_awaited_once()
        self.agent_factory.assert_not_called()

    async def test_city_guide_standalone_failure_closes_both_connections(self) -> None:
        self.test_agent.run.side_effect = RuntimeError("retrieval failed")
        with (
            patch("builtins.print") as output,
            self.assertRaisesRegex(RuntimeError, "retrieval failed"),
        ):
            await guide.main()
        output.assert_not_called()
        self.kb.__aexit__.assert_awaited_once()
        self.client.client.__aexit__.assert_awaited_once()

    async def test_city_guide_standalone_cancellation_closes_both_connections(self) -> None:
        self.test_agent.run.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
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


class NoteReaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, ENV, clear=True))
        self.client = MagicMock()
        self.client.client = managed_resource()
        self.client_factory = self.enterContext(
            patch.object(note_reader, "OpenAIChatClient", return_value=self.client)
        )
        self.note = note_reader.SecretNote(
            language="Klingon", translation="Hello, friend! Secret code: Qapla'", password="Qapla'",
        )
        self.reader = MagicMock(spec=Agent)
        self.reader.run = AsyncMock(return_value=MagicMock(value=self.note))

    def test_sample_note_is_a_public_https_image(self) -> None:
        self.assertTrue(note_reader.SAMPLE_NOTE_URL.startswith("https://"))
        self.assertTrue(note_reader.SAMPLE_NOTE_URL.endswith(".png"))

    async def test_agent_uses_main_model_and_closes_client(self) -> None:
        async with note_reader.build_note_reader_agent() as agent:
            self.assertIsInstance(agent, Agent)
        self.client_factory.assert_called_once_with(
            azure_endpoint=ENV["AZURE_OPENAI_ENDPOINT"],
            api_key=ENV["AZURE_OPENAI_API_KEY"],
            model=ENV["AZURE_OPENAI_DEPLOYMENT_NAME"],
        )
        self.client.client.__aexit__.assert_awaited_once()

    async def test_read_note_sends_image_url_and_requests_structured_output(self) -> None:
        for url, media_type in (
            ("https://notes.invalid/door.jpg?sig=abc", "image/jpeg"),
            ("https://notes.invalid/door", "image/png"),
        ):
            with self.subTest(url=url):
                result = await note_reader.read_note(self.reader, url)
                self.assertIs(result, self.note)
                message = self.reader.run.await_args.args[0]
                self.assertEqual(message.role, "user")
                image = message.contents[1]
                self.assertEqual(image.type, "uri")
                self.assertEqual(image.uri, url)
                self.assertEqual(image.media_type, media_type)
        self.assertEqual(
            self.reader.run.await_args.kwargs["options"],
            {"response_format": note_reader.SecretNote},
        )

    async def test_tool_returns_structured_note_as_json(self) -> None:
        tool = note_reader.build_note_reader_tool(self.reader)
        self.assertEqual(tool.name, "read_secret_note")
        self.assertIn("image_url", tool.parameters()["properties"])
        result = await tool.invoke(arguments={"image_url": "https://notes.invalid/door.png"})
        self.assertEqual(
            note_reader.SecretNote.model_validate_json(result[0].text), self.note,
        )
        self.assertEqual(
            self.reader.run.await_args.args[0].contents[1].uri, "https://notes.invalid/door.png",
        )

    async def test_main_prints_language_translation_and_password(self) -> None:
        reader = managed_resource()
        reader.run = self.reader.run
        with (
            patch.object(note_reader, "build_note_reader_agent", return_value=reader),
            patch("builtins.print") as output,
        ):
            await note_reader.main()
        self.assertEqual(
            reader.run.await_args.args[0].contents[1].uri, note_reader.SAMPLE_NOTE_URL,
        )
        printed = [call.args[0] for call in output.call_args_list]
        self.assertEqual(printed, [
            "Language: Klingon",
            "Translation: Hello, friend! Secret code: Qapla'",
            "Password: Qapla'",
        ])
        reader.__aexit__.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
