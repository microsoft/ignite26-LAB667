"""Exercise Search-style optional Tasks metadata through the real MCP client."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx2
from agent_framework.exceptions import ToolExecutionException
from mcp import Client, types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_city_guide as guide


class CityGuideMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_task_metadata_is_normalized_without_mutating_sdk_cache(self) -> None:
        original = types.ListToolsResult(
            tools=[
                types.Tool(
                    name=name, input_schema={"type": "object"},
                    execution=types.ToolExecution(task_support=support),
                )
                for name, support in [
                    ("knowledge_base_retrieve", "optional"),
                    ("another_tool", "optional"),
                ]
            ],
            next_cursor="next-page",
        )
        client = guide.CityGuideClient("https://search.invalid/mcp")
        with patch.object(Client, "list_tools", AsyncMock(return_value=original)) as listing:
            result = await client.list_tools(cursor="page")
        listing.assert_awaited_once_with(cursor="page")
        self.assertIsNone(result.tools[0].execution)
        self.assertEqual(original.tools[0].execution.task_support, "optional")
        self.assertEqual(result.tools[1].execution.task_support, "optional")
        self.assertEqual(result.next_cursor, "next-page")
        self.assertEqual(result.tools[0].input_schema, original.tools[0].input_schema)

    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, {
            "AZURE_SEARCH_ENDPOINT": "https://search.invalid",
            "AZURE_SEARCH_KNOWLEDGE_BASE_NAME": "cityguide",
            "AZURE_SEARCH_KEY": "test-key",
        }))
        self.support = "optional"
        self.calls = []
        self.clients = []
        self.fail_retrieval = False
        self.notify_tools_changed = False
        self.hide_tool = False
        self.list_requests = 0
        self.pings = 0

        def respond(request: httpx2.Request) -> httpx2.Response:
            self.assertEqual(request.headers["api-key"], "test-key")
            self.assertEqual(request.url.host, "search.invalid")
            if request.method != "POST":
                return httpx2.Response(405)
            body = json.loads(request.content)
            method = body["method"]
            if "id" not in body:
                return httpx2.Response(202)
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "Search fixture", "version": "1"},
                }
            elif method == "tools/list":
                self.list_requests += 1
                result = {"tools": [{
                    "name": "knowledge_base_retrieve",
                    "description": "Retrieve from the city guide.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                    "execution": {"taskSupport": self.support},
                }]}
                if self.hide_tool:
                    result["tools"] = []
            elif method == "tools/call":
                self.calls.append(body["params"])
                if self.fail_retrieval:
                    return httpx2.Response(503)
                result = {"content": [{"type": "text", "text": "Dolores Park is in the Mission District."}]}
                if self.notify_tools_changed:
                    self.hide_tool = True
                    notification = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
                    reply = {"jsonrpc": "2.0", "id": body["id"], "result": result}
                    return httpx2.Response(
                        200, headers={"content-type": "text/event-stream"},
                        content=f"data: {json.dumps(notification)}\n\ndata: {json.dumps(reply)}\n\n",
                    )
            elif method == "ping":
                self.pings += 1
                result = {}
            else:
                raise AssertionError(f"Unexpected MCP method: {method}")
            return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        def http_client(**kwargs):
            client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)
            self.clients.append(client)
            return client

        self.enterContext(patch.object(guide, "AsyncClient", side_effect=http_client))

    async def test_optional_tasks_tool_is_discovered_and_called_synchronously(self) -> None:
        with warnings.catch_warnings(record=True) as captured, self.assertNoLogs("agent_framework._mcp", "WARNING"):
            warnings.simplefilter("always")
            async with guide.build_city_guide_tool() as kb:
                self.assertEqual([tool.name for tool in kb.functions], ["knowledge_base_retrieve"])
                result = await kb.functions[0].invoke(query="Where is Dolores Park?")
                self.assertEqual([content.text for content in result], [
                    "Dolores Park is in the Mission District.",
                ])
        self.assertEqual(captured, [])
        self.assertGreater(self.pings, 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["name"], "knowledge_base_retrieve")
        self.assertEqual(self.calls[0]["arguments"], {"query": "Where is Dolores Park?"})
        self.assertNotIn("task", self.calls[0])
        self.assertTrue(all(client.is_closed for client in self.clients))

    async def test_legacy_notifications_refresh_the_tool_catalog(self) -> None:
        self.notify_tools_changed = True
        async with guide.build_city_guide_tool() as kb:
            await kb.call_tool("knowledge_base_retrieve", query="Where is Dolores Park?")
            async with asyncio.timeout(5):
                while kb.functions:
                    await asyncio.sleep(.01)
            self.assertGreaterEqual(self.list_requests, 2)
        self.assertTrue(all(client.is_closed for client in self.clients))

    async def test_setup_filter_preserves_other_warnings_errors_and_other_tasks(self) -> None:
        logger = logging.getLogger("agent_framework._mcp")
        notice = (
            "Automatic legacy catalog refresh is unavailable for a caller-owned Client; "
            "configure legacy notification handling when constructing the Client."
        )
        filters_before = list(logger.filters)
        ready = asyncio.Event()

        async def unrelated_connection() -> None:
            await ready.wait()
            logger.warning(notice)

        other = asyncio.create_task(unrelated_connection())
        with self.assertLogs(logger, "WARNING") as logged:
            with guide.configured_legacy_notifications():
                logger.warning(notice)
                logger.warning("Retrieval warning")
                logger.error("Authentication failed")
                ready.set()
                await other
            logger.warning(notice)
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["Retrieval warning", "Authentication failed", notice, notice],
        )
        self.assertEqual(logger.filters, filters_before)

    async def test_required_tasks_stay_blocked_and_connections_close(self) -> None:
        self.support = "required"
        with self.assertRaises(ExceptionGroup) as raised:
            async with guide.build_city_guide_tool():
                self.fail("A task-required tool must not become callable.")
        self.assertIsNotNone(raised.exception.subgroup(
            lambda error: isinstance(error, RuntimeError) and "required MCP Tasks are not supported" in str(error)
        ))
        self.assertEqual(self.calls, [])
        self.assertTrue(all(client.is_closed for client in self.clients))

    async def test_unadapted_framework_reproduces_optional_task_skip(self) -> None:
        with patch.object(guide, "CityGuideClient", Client), self.assertRaises(ExceptionGroup) as raised:
            async with guide.build_city_guide_tool():
                self.fail("The unadapted framework should reproduce the discovery failure.")
        self.assertIsNotNone(raised.exception.subgroup(RuntimeError))
        self.assertEqual(self.calls, [])
        self.assertTrue(all(client.is_closed for client in self.clients))

    async def test_retrieval_failure_is_not_converted_to_an_answer(self) -> None:
        self.fail_retrieval = True
        with self.assertRaises(ExceptionGroup) as raised:
            async with guide.build_city_guide_tool() as kb:
                await kb.call_tool("knowledge_base_retrieve", query="Where is Dolores Park?")
        self.assertIsNotNone(raised.exception.subgroup(ToolExecutionException))
        self.assertTrue(all(client.is_closed for client in self.clients))
