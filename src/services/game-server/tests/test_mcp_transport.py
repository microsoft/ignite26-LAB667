"""Exercise the real per-game MCP HTTP dispatcher using fake Table storage."""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from mcp import Client
from starlette.testclient import TestClient
import uvicorn

from test_admin_auth import fake_service
from test_game_versions import story
import server
import storage


class MCPTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        service, self.tables = fake_service()
        self.patch = patch.object(storage, "_service", service)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        storage.create_game("test-city", "Test city", quests=story())
        self.client = TestClient(server.build_app(), base_url="https://workshop.example")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def rpc(self, method: str, params: dict, slug: str = "test-city", version: str = "2025-03-26") -> dict:
        response = self.client.post(
            f"/{slug}/mcp",
            headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": version},
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("mcp-session-id", response.headers)
        self.assertIn("text/event-stream", response.headers["content-type"])
        messages = [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines()
                    if line.startswith("data: ")]
        replies = [message for message in messages if message.get("id") == 1]
        self.assertEqual(len(replies), 1, response.text)
        return replies[0]

    def tool(self, name: str, arguments: dict, slug: str = "test-city") -> dict:
        reply = self.rpc("tools/call", {"name": name, "arguments": arguments}, slug)
        self.assertNotIn("error", reply)
        result = reply["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        return result["structuredContent"]

    def test_legacy_initialization_tool_contract_and_prompt(self) -> None:
        for version in ("2024-11-05", "2025-03-26", "2025-11-25"):
            result = self.rpc("initialize", {
                "protocolVersion": version, "capabilities": {},
                "clientInfo": {"name": "workshop-test", "version": "1"},
            }, version=version)["result"]
            self.assertEqual(result["protocolVersion"], version)
            self.assertEqual(result["serverInfo"]["name"], "game-test-city")
            self.assertIn("Test city", result["instructions"])
        listed = self.rpc("tools/list", {})["result"]["tools"]
        self.assertEqual({tool["name"] for tool in listed}, {
            "begin_session", "resume_player", "register_player", "start_quest",
            "submit_mission_answer", "abandon_quest", "get_leaderboard", "get_player_status",
        })
        register = next(tool for tool in listed if tool["name"] == "register_player")
        self.assertEqual(register["inputSchema"]["required"], ["name"])
        self.assertEqual(register["inputSchema"]["properties"]["name"]["minLength"], 1)
        self.assertEqual(self.tool("begin_session", {})["status"], "awaiting_identity")
        prompts = self.rpc("prompts/list", {})["result"]["prompts"]
        self.assertEqual([prompt["name"] for prompt in prompts], ["game_play_prompt"])
        prompt = self.rpc("prompts/get", {"name": "game_play_prompt"})["result"]
        self.assertEqual(prompt["messages"][0]["content"]["text"],
                         server._game_play_prompt_for(storage.get_game("test-city")))

    def test_game_isolation_live_creation_and_cache_replacement(self) -> None:
        player = self.tool("register_player", {"name": "Alice"})
        storage.create_game("another-city", "Another city", quests=story("NEW", "Another story"))
        result = self.tool("begin_session", {"player_id": player["player_id"]}, "another-city")
        self.assertEqual(result["status"], "unknown_player_id")
        self.assertEqual(result["game"], "Another city")
        self.assertEqual(self.client.post("/missing/mcp").status_code, 404)
        storage.delete_game("another-city")
        self.assertEqual(self.client.post("/another-city/mcp").status_code, 404)
        storage.create_game("another-city", "Replacement", quests=story())
        self.assertEqual(self.tool("begin_session", {}, "another-city")["game"], "Replacement")
        entity = self.tables[storage.GAMES_TABLE].get_entity("games", "another-city")
        entity["display_name"] = "Renamed city"
        self.tables[storage.GAMES_TABLE].upsert_entity(entity)
        self.assertEqual(self.tool("begin_session", {}, "another-city")["game"], "Renamed city")
        games = self.client.get("/").json()["games"]
        self.assertEqual({game["mcp_url"] for game in games}, {"/test-city/mcp", "/another-city/mcp"})

    def test_http_players_remain_pinned_after_publication(self) -> None:
        old = self.tool("register_player", {"name": "Alice"})["player_id"]
        draft = storage.save_draft("test-city", story("NEW", "New story"), storage.load_draft("test-city")["revision"])
        storage.publish_draft("test-city", draft["revision"])
        new = self.tool("register_player", {"name": "Beatrice"})["player_id"]
        for player_id, answer, title in ((old, "OLD", "Original story"), (new, "NEW", "New story")):
            resumed = self.tool("resume_player", {"player_id": player_id})
            self.assertEqual(resumed["quest_name"], title)
            self.tool("start_quest", {"player_id": player_id})
            result = self.tool("submit_mission_answer", {"player_id": player_id, "answer": answer})
            self.assertEqual(result["status"], "quest_complete")

    def test_invalid_tools_and_arguments_return_protocol_errors(self) -> None:
        for name, arguments in (("missing_tool", {}), ("register_player", {}), ("register_player", {"name": ""})):
            reply = self.rpc("tools/call", {"name": name, "arguments": arguments})
            self.assertTrue("error" in reply or reply.get("result", {}).get("isError"), reply)

    def test_cache_replacement_drains_inflight_requests_without_blocking_other_tools(self) -> None:
        self.tool("begin_session", {})
        entered, release, replaced = threading.Event(), threading.Event(), threading.Event()
        get_player = storage.get_player
        build = server.build_mcp_for_game

        def slow_player(slug, player_id):
            if player_id == "slow":
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release the slow storage call")
            return get_player(slug, player_id)

        def rebuild(game):
            app = build(game)
            if game["display_name"] == "Renamed city":
                replaced.set()
            return app

        with patch.object(storage, "get_player", side_effect=slow_player), \
                patch.object(server, "build_mcp_for_game", side_effect=rebuild), \
                ThreadPoolExecutor(max_workers=3) as pool:
            old_request = pool.submit(self.tool, "begin_session", {"player_id": "slow"})
            try:
                self.assertTrue(entered.wait(3))
                fast = pool.submit(self.tool, "begin_session", {})
                self.assertEqual(fast.result(timeout=3)["status"], "awaiting_identity")
                game = self.tables[storage.GAMES_TABLE].get_entity("games", "test-city")
                game["display_name"] = "Renamed city"
                self.tables[storage.GAMES_TABLE].upsert_entity(game)
                new_request = pool.submit(self.tool, "begin_session", {})
                self.assertTrue(replaced.wait(3))
                self.assertFalse(new_request.done())
            finally:
                release.set()
            self.assertEqual(old_request.result(timeout=3)["game"], "Test city")
            self.assertEqual(new_request.result(timeout=3)["game"], "Renamed city")

    def test_sdk_client_over_real_http_legacy_and_modern(self) -> None:
        async def exercise() -> None:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                url = f"http://127.0.0.1:{listener.getsockname()[1]}/test-city/mcp"
                http_server = uvicorn.Server(uvicorn.Config(server.build_app(), log_level="error"))
                task = asyncio.create_task(http_server.serve(sockets=[listener]))
                try:
                    async with asyncio.timeout(20):
                        while not http_server.started:
                            if task.done():
                                await task
                                self.fail("HTTP server exited before startup")
                            await asyncio.sleep(.01)
                        for mode in ("legacy", "auto", "2026-07-28"):
                            async with Client(url, mode=mode, read_timeout_seconds=5) as client:
                                tools = await client.list_tools()
                                self.assertEqual(len(tools.tools), 8)
                                prompt = await client.get_prompt("game_play_prompt")
                                self.assertEqual(len(prompt.messages), 1)
                                results = await asyncio.gather(*(client.call_tool("begin_session", {}) for _ in range(3)))
                                for result in results:
                                    self.assertFalse(result.is_error)
                                    self.assertEqual(result.structured_content["status"], "awaiting_identity")
                finally:
                    http_server.should_exit = True
                    await asyncio.wait_for(task, timeout=5)

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
