"""Test the real A2A routes with a fake agent and no external services."""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.types import AgentCard, TaskNotCancelableError
from agent_framework import Agent, AgentResponse, Message
from agent_framework.a2a import A2AAgent
from google.protobuf.json_format import ParseDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}):
    import server
    from src.agents.player import agent_agent42


REPLY = "Weather: clear\nrecommendation: bike\nrecommendation code: a1b2c3d4e5f6g7h"
URL = "http://agent42.test/"


class A2ATransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.agent = MagicMock(spec=Agent)
        self.agent.run = AsyncMock(
            return_value=AgentResponse(messages=[Message("assistant", [REPLY])])
        )
        with patch.object(server, "build_agent", return_value=self.agent), patch.dict(
            os.environ, {"AGENT42_PUBLIC_URL": URL}, clear=True
        ):
            self.app = server.build_app()
        await self.enterAsyncContext(self.app.router.lifespan_context(self.app))
        self.client = await self.enterAsyncContext(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app), base_url=URL
            )
        )

    async def rpc(self, method: str, params: dict, version: str = "1.0") -> dict:
        response = await self.client.post(
            "/",
            headers={"A2A-Version": version},
            json={"jsonrpc": "2.0", "id": "test-request", "method": method, "params": params},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["id"], "test-request")
        return result

    def message_params(self) -> dict:
        return {
            "message": {
                "messageId": "test-message",
                "contextId": "trip-context",
                "role": "ROLE_USER",
                "parts": [{"text": "How do I get to the park?"}],
            }
        }

    async def test_agent_card_discovery_and_client(self) -> None:
        response = await self.client.get("/.well-known/agent-card.json")
        self.assertEqual(response.status_code, 200)
        card_json = response.json()
        self.assertEqual(card_json["name"], "Agent42")
        self.assertEqual(card_json["supportedInterfaces"], [{
            "url": URL, "protocolBinding": "JSONRPC", "protocolVersion": "1.0",
        }])
        self.assertEqual(card_json["capabilities"], {
            "streaming": False, "pushNotifications": False,
        })
        self.assertEqual(card_json["skills"][0]["id"], "transport-advice")
        card = ParseDict(card_json, AgentCard())
        remote = A2AAgent(name="Agent42", agent_card=card, http_client=self.client)
        result = await remote.run("A route please")
        self.assertEqual(result.text, REPLY)
        self.agent.run.assert_awaited_once_with("A route please")

    async def test_v1_message_preserves_text_and_context(self) -> None:
        response = await self.rpc("SendMessage", self.message_params())
        self.assertNotIn("error", response)
        message = response["result"]["message"]
        self.assertEqual(message["parts"], [{"text": REPLY}])
        self.assertEqual(message["role"], "ROLE_AGENT")
        self.assertEqual(message["contextId"], "trip-context")
        self.assertTrue(message["messageId"])
        self.assertNotIn("taskId", message)
        self.agent.run.assert_awaited_once_with("How do I get to the park?")

    async def test_legacy_message_send_remains_supported(self) -> None:
        params = self.message_params()
        params["message"]["role"] = "user"
        params["message"]["parts"][0]["kind"] = "text"
        response = await self.rpc("message/send", params, version="0.3")
        self.assertNotIn("error", response)
        self.assertEqual(response["result"]["parts"], [{"kind": "text", "text": REPLY}])
        self.assertEqual(response["result"]["role"], "agent")

    async def test_player_agent_and_tool_use_current_client(self) -> None:
        def remote_agent(**kwargs) -> A2AAgent:
            return A2AAgent(**kwargs, http_client=self.client)

        with patch.dict(os.environ, {"AGENT42_URL": URL}), patch.object(
            agent_agent42, "A2AAgent", side_effect=remote_agent
        ):
            remote = agent_agent42.build_agent42_agent()
            session = remote.create_session()
            for question in ("First trip", "Second trip"):
                self.assertEqual((await remote.run(question, session=session)).text, REPLY)
            tool = agent_agent42.build_agent42_tool()
            result = await tool.invoke(question="A third trip")
            self.assertEqual([content.text for content in result], [REPLY])
        self.assertEqual(self.agent.run.await_count, 3)

    async def test_execution_failure_is_a_protocol_error(self) -> None:
        self.agent.run.side_effect = RuntimeError("test model failure")
        with self.assertLogs("a2a", level="ERROR"):
            response = await self.rpc("SendMessage", self.message_params())
        self.assertNotIn("result", response)
        self.assertEqual(response["error"]["code"], -32603)

    async def test_empty_response_is_not_success(self) -> None:
        self.agent.run.return_value = AgentResponse()
        with self.assertLogs(level="ERROR"):
            response = await self.rpc("SendMessage", self.message_params())
        self.assertNotIn("result", response)
        self.assertEqual(response["error"]["code"], -32603)

    async def test_streaming_and_missing_tasks_do_not_run_agent(self) -> None:
        for method, params, error_code in (
            ("SendStreamingMessage", self.message_params(), -32004),
            ("GetTask", {"id": "missing-task"}, -32001),
            ("CancelTask", {"id": "missing-task"}, -32001),
        ):
            with self.subTest(method=method):
                response = await self.rpc(method, params)
                self.assertIn("error", response)
                self.assertEqual(response["error"]["code"], error_code)
                self.assertNotIn("result", response)
        self.agent.run.assert_not_awaited()

    async def test_cancel_executor_is_explicitly_unsupported(self) -> None:
        executor = server.AgentFrameworkExecutor(self.agent)
        with self.assertRaises(TaskNotCancelableError):
            await executor.cancel(
                RequestContext(ServerCallContext()), MagicMock(spec=EventQueue)
            )

    async def test_shutdown_closes_handler_tasks(self) -> None:
        with patch.object(server, "build_agent", return_value=self.agent), patch.dict(
            os.environ, {"AGENT42_PUBLIC_URL": URL}, clear=True
        ):
            app = server.build_app()
        before = asyncio.all_tasks()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                remote = A2AAgent(name="Agent42", url=URL, http_client=client)
                self.assertEqual((await remote.run("One last trip")).text, REPLY)
        remaining = {task for task in asyncio.all_tasks() - before if not task.done()}
        self.assertFalse(remaining, remaining)

    async def test_default_advertised_host_is_localhost(self) -> None:
        with patch.object(server, "build_agent", return_value=self.agent), patch.dict(
            os.environ, {}, clear=True
        ):
            app = server.build_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=URL
            ) as client:
                card = (await client.get("/.well-known/agent-card.json")).json()
        self.assertEqual(card["supportedInterfaces"][0]["url"], "http://localhost:8042")


if __name__ == "__main__":
    unittest.main()
