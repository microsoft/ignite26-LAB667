"""Exercise the real per-game MCP HTTP dispatcher using fake Table storage."""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import unittest
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from unittest.mock import patch

from agent_framework import Content, MCPStreamableHTTPTool
from starlette.testclient import TestClient
import uvicorn

from test_admin_auth import fake_service
from test_game_versions import story
import server
import storage
import player_identity


class MCPTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        service, self.tables = fake_service()
        self.patch = patch.object(storage, "_service", service)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        storage.create_game("test-city", "Test city", quests=story())
        self.api_key, _ = player_identity.register_player("test-city", "Alice")
        self.client = TestClient(server.build_app(), base_url="https://workshop.example")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.initial_game_urls = {f"/{game['slug']}/mcp" for game in storage.list_games()}

    def rpc(
        self, method: str, params: dict, slug: str = "test-city",
        version: str = "2025-03-26", api_key: str | None = None,
    ) -> dict:
        response = self.client.post(
            f"/{slug}/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": version,
                "Authorization": f"Bearer {api_key or self.api_key}",
            },
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

    def tool(
        self, name: str, arguments: dict, slug: str = "test-city",
        api_key: str | None = None,
    ) -> dict:
        reply = self.rpc(
            "tools/call", {"name": name, "arguments": arguments}, slug,
            api_key=api_key,
        )
        self.assertNotIn("error", reply)
        result = reply["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        return result["structuredContent"]

    def test_authenticated_initialization_tool_contract_and_prompt(self) -> None:
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
            "begin_session", "resume_player", "start_quest",
            "submit_mission_answer", "abandon_quest", "get_leaderboard", "get_player_status",
        })
        self.assertEqual(self.tool("begin_session", {})["status"], "known_player")
        for tool in listed:
            self.assertNotIn("player_id", tool["inputSchema"].get("properties", {}))
        prompts = self.rpc("prompts/list", {})["result"]["prompts"]
        self.assertEqual([prompt["name"] for prompt in prompts], ["game_play_prompt"])
        prompt = self.rpc("prompts/get", {"name": "game_play_prompt"})["result"]
        self.assertEqual(prompt["messages"][0]["content"]["text"],
                         server._game_play_prompt_for(storage.get_game("test-city")))

    def test_player_auth_and_agent42_timeline_endpoint(self) -> None:
        self.assertEqual(self.client.get("/player/auth").status_code, 401)
        self.assertEqual(
            self.client.get(
                "/player/auth",
                headers={"Authorization": "Bearer invalid"},
            ).status_code,
            401,
        )
        auth = self.client.get(
            "/player/auth",
            headers={"Authorization": "Bearer " + self.api_key},
        )
        self.assertEqual(auth.status_code, 200, auth.text)
        self.assertEqual(auth.headers["cache-control"], "no-store")
        self.assertEqual(auth.json()["slug"], "test-city")
        self.assertEqual(auth.json()["name"], "Alice")
        self.assertNotIn(self.api_key, auth.text)

        event = self.client.post(
            "/player/events/agent42",
            headers={"Authorization": "Bearer " + self.api_key},
            json={
                "summary": (
                    "  Weather: 14 C, light rain  \n\n"
                    "  Reasoning: Take the bike via the park.  \n"
                    "  recommendation: bike  \n"
                    "  recommendation code: abc123def456ghi  "
                )
            },
        )
        self.assertEqual(event.status_code, 200, event.text)
        self.assertEqual(event.headers["cache-control"], "no-store")
        timeline = storage.get_player("test-city", self.api_key)["timeline"]
        self.assertEqual(timeline[-1]["type"], "agent42")
        self.assertEqual(
            timeline[-1]["detail"],
            (
                "Weather: 14 C, light rain\n\n"
                "Reasoning: Take the bike via the park.\n"
                "recommendation: bike\n"
                "recommendation code: abc123def456ghi"
            ),
        )
        self.assertEqual(timeline[-1]["route_ref"], "abc123def456ghi")
        safe_timeline = player_identity.player_state("test-city", self.api_key)["timeline"]
        self.assertNotIn("route_ref", safe_timeline[-1])
        self.assertNotIn("abc123def456ghi", safe_timeline[-1]["detail"])
        self.assertNotIn(self.api_key, json.dumps(timeline))

        self.assertEqual(
            self.client.post(
                "/player/events/agent42",
                headers={"Authorization": "Bearer " + self.api_key},
                json={"summary": " "},
            ).status_code,
            422,
        )

    def test_game_isolation_live_creation_and_cache_replacement(self) -> None:
        storage.create_game("another-city", "Another city", quests=story("NEW", "Another story"))
        unauthorized = self.client.post(
            "/another-city/mcp",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        self.assertEqual(unauthorized.status_code, 401)
        another_key, _ = player_identity.register_player("another-city", "Beatrice")
        result = self.tool("begin_session", {}, "another-city", another_key)
        self.assertEqual(result["status"], "known_player")
        self.assertEqual(result["game"], "Another city")
        self.assertEqual(self.client.post("/missing/mcp").status_code, 404)
        storage.delete_game("another-city")
        self.assertEqual(self.client.post("/another-city/mcp").status_code, 404)
        storage.create_game("another-city", "Replacement", quests=story())
        replacement_key, _ = player_identity.register_player("another-city", "Carla")
        self.assertEqual(self.tool("begin_session", {}, "another-city", replacement_key)["game"], "Replacement")
        entity = self.tables[storage.GAMES_TABLE].get_entity("games", "another-city")
        entity["display_name"] = "Renamed city"
        self.tables[storage.GAMES_TABLE].upsert_entity(entity)
        self.assertEqual(self.tool("begin_session", {}, "another-city", replacement_key)["game"], "Renamed city")
        games = self.client.get("/").json()["games"]
        self.assertEqual({game["mcp_url"] for game in games}, self.initial_game_urls | {"/another-city/mcp"})

    def test_http_players_remain_pinned_after_publication(self) -> None:
        old = self.api_key
        draft = storage.save_draft("test-city", story("NEW", "New story"), storage.load_draft("test-city")["revision"])
        storage.publish_draft("test-city", draft["revision"])
        new, _ = player_identity.register_player("test-city", "Beatrice")
        for api_key, answer, title in ((old, "OLD", "Original story"), (new, "NEW", "New story")):
            resumed = self.tool("resume_player", {}, api_key=api_key)
            self.assertEqual(resumed["quest_name"], title)
            self.tool("start_quest", {}, api_key=api_key)
            result = self.tool("submit_mission_answer", {"answer": answer}, api_key=api_key)
            self.assertEqual(result["status"], "quest_complete")

    def test_invalid_tools_and_arguments_return_protocol_errors(self) -> None:
        for name, arguments in (("missing_tool", {}), ("submit_mission_answer", {}), ("submit_mission_answer", {"answer": ""})):
            reply = self.rpc("tools/call", {"name": name, "arguments": arguments})
            self.assertTrue("error" in reply or reply.get("result", {}).get("isError"), reply)

    def test_cache_replacement_drains_inflight_requests_without_blocking_other_tools(self) -> None:
        self.tool("begin_session", {})
        fast_key, _ = player_identity.register_player("test-city", "Fast player")
        entered, release, replaced = threading.Event(), threading.Event(), threading.Event()
        get_player = storage.get_player
        build = server.build_mcp_for_game
        slow_reads = 0

        def slow_player(slug, player_id):
            nonlocal slow_reads
            if player_id == self.api_key:
                slow_reads += 1
            if player_id == self.api_key and slow_reads == 2:
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
            old_request = pool.submit(self.tool, "begin_session", {})
            try:
                self.assertTrue(entered.wait(3))
                fast = pool.submit(self.tool, "begin_session", {}, "test-city", fast_key)
                self.assertEqual(fast.result(timeout=3)["status"], "known_player")
                game = self.tables[storage.GAMES_TABLE].get_entity("games", "test-city")
                game["display_name"] = "Renamed city"
                self.tables[storage.GAMES_TABLE].upsert_entity(game)
                new_request = pool.submit(self.tool, "begin_session", {}, "test-city", fast_key)
                self.assertTrue(replaced.wait(3))
                self.assertFalse(new_request.done())
            finally:
                release.set()
            self.assertEqual(old_request.result(timeout=3)["game"], "Test city")
            self.assertEqual(new_request.result(timeout=3)["game"], "Renamed city")

    @asynccontextmanager
    async def serve_game(self) -> AsyncGenerator[str, None]:
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
                    yield url
            finally:
                http_server.should_exit = True
                await asyncio.wait_for(task, timeout=5)

    def test_real_http_rejects_missing_bearer_key(self) -> None:
        async def exercise() -> None:
            import httpx
            async with self.serve_game() as url, httpx.AsyncClient() as client:
                response = await client.post(url)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")

        asyncio.run(exercise())

    def framework_text(self, result: object) -> str:
        self.assertIsInstance(result, list)
        assert isinstance(result, list)
        self.assertEqual(len(result), 1)
        content = result[0]
        self.assertIsInstance(content, Content)
        assert isinstance(content, Content)
        self.assertEqual(content.type, "text")
        assert isinstance(content.text, str)
        return content.text

    def test_agent_framework_mcp2_discovery_prompt_and_gameplay(self) -> None:
        async def exercise() -> None:
            async with self.serve_game() as url, MCPStreamableHTTPTool(
                name="Gaming MCP Server",
                url=url,
                static_headers={"Authorization": f"Bearer {self.api_key}"},
            ) as game:
                tools = {tool.name: tool for tool in game.functions}
                self.assertEqual(set(tools), {
                    "begin_session", "resume_player", "start_quest",
                    "submit_mission_answer", "abandon_quest", "get_leaderboard", "get_player_status",
                    "game_play_prompt",
                })
                prompt = await game.get_prompt("game_play_prompt")
                self.assertEqual(prompt, server._game_play_prompt_for(storage.get_game("test-city")))
                self.assertEqual(self.framework_text(await tools["game_play_prompt"].invoke()), prompt)

                async def call(name: str, **arguments: str) -> dict:
                    result = await tools[name].invoke(**arguments)
                    return json.loads(self.framework_text(result))

                self.assertEqual((await call("begin_session"))["status"], "known_player")
                started = await call("start_quest")
                self.assertEqual(started["status"], "quest_started")
                self.assertEqual(started["mission_type"], "question")
                self.assertNotIn("valid_answers", started)
                rejected = await call("submit_mission_answer", answer="WRONG")
                self.assertEqual(rejected["status"], "mission_answer_rejected")
                completed = await call("submit_mission_answer", answer="OLD")
                self.assertEqual(completed["status"], "quest_complete")
                status = await game.call_tool("get_player_status")
                self.assertEqual(json.loads(self.framework_text(status))["status"], "complete")

        asyncio.run(exercise())

    def test_agent_framework_mcp2_filtered_tools_without_prompts(self) -> None:
        async def exercise() -> None:
            async with self.serve_game() as url, MCPStreamableHTTPTool(
                name="Filtered MCP connection",
                url=url,
                static_headers={"Authorization": f"Bearer {self.api_key}"},
                allowed_tools=["get_player_status"],
                load_prompts=False,
            ) as game:
                self.assertEqual([tool.name for tool in game.functions], ["get_player_status"])
                result = await game.call_tool("get_player_status")
                self.assertEqual(json.loads(self.framework_text(result))["status"], "registered")

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
