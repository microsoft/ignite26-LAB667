"""Verify shared route caching without calling Azure services."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools


class RouteCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        tools._route_cache.clear()
        self.addCleanup(tools._route_cache.clear)
        self.enterContext(patch.object(tools, "_route_cache_lock", asyncio.Lock()))
        self.enterContext(patch.object(
            tools, "_static_map_cache", tools._MemoryCache[bytes](1800, 128),
        ))
        self.clock = self.enterContext(patch.object(tools, "monotonic", return_value=100.0))
        self.enterContext(patch.object(tools, "_azure_maps_key", return_value="test-key"))

        async def geocode(client: httpx.AsyncClient, query: str) -> tuple[float, float, str]:
            return (37.77 if query == "Origin" else 37.78), -122.42, query

        self.enterContext(patch.object(tools, "_geocode_azure", side_effect=geocode))
        self.response = httpx.Response(
            200, request=httpx.Request("GET", tools.AZ_ROUTE_URL),
            json={"routes": [{
                "summary": {
                    "lengthInMeters": 1200, "travelTimeInSeconds": 300,
                    "trafficDelayInSeconds": 60, "departureTime": "2026-11-13T14:00:00Z",
                },
                "legs": [{"summary": {"lengthInMeters": 1200}, "points": [
                    {"latitude": 37.77, "longitude": -122.42},
                    {"latitude": 37.78, "longitude": -122.42},
                ]}],
                "guidance": {"instructions": [{"message": "Go north"}]},
            }]},
        )
        self.get = self.enterContext(patch.object(
            httpx.AsyncClient, "get", AsyncMock(return_value=self.response),
        ))

    async def test_aliases_share_route_but_preserve_call_details_and_nested_data(self) -> None:
        first = await tools.get_route("Origin", "Destination", "taxi")
        self.assertEqual(first["traffic_delay_seconds"], 60)
        first["steps"][0]["text"] = "changed"
        second = await tools.get_route("Origin", "Destination", "car")
        self.assertEqual(second["mode"], "car")
        self.assertEqual(second["steps"][0]["text"], "Go north")
        self.assertEqual(second["departure_time"], "2026-11-13T14:00:00Z")
        self.get.assert_awaited_once()
        self.assertEqual(self.get.call_args.kwargs["params"]["traffic"], "true")
        await tools.get_route("Origin", "Destination", "walking")
        await tools.get_route("Destination", "Origin", "car")
        self.assertEqual(self.get.await_count, 3)

    async def test_expires_exactly_after_thirty_minutes(self) -> None:
        await tools.get_route("Origin", "Destination")
        self.clock.return_value = 1899.999
        await tools.get_route("Origin", "Destination")
        self.get.assert_awaited_once()
        self.clock.return_value = 1900.0
        await tools.get_route("Origin", "Destination")
        self.assertEqual(self.get.await_count, 2)

    async def test_failed_refreshes_are_not_cached_or_served_stale(self) -> None:
        await tools.get_route("Origin", "Destination")
        self.clock.return_value = 1900.0
        failures = [
            httpx.Response(429, text="rate limit"),
            httpx.Response(200, text="not JSON"),
            httpx.Response(200, json={"routes": []}),
            httpx.ConnectError("unavailable"),
        ]
        for failure in failures:
            with self.subTest(failure=str(failure)):
                self.get.side_effect = [failure, self.response]
                result = await tools.get_route("Origin", "Destination")
                self.assertIn("error", result)
                recovered = await tools.get_route("Origin", "Destination")
                self.assertEqual(recovered["travel_time_seconds"], 300)
                self.clock.return_value += 1800
        self.assertEqual(self.get.await_count, 9)

    async def test_concurrent_requests_share_one_route(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def get(*args: object, **kwargs: object) -> httpx.Response:
            started.set()
            await release.wait()
            return self.response

        self.get.side_effect = get
        async with asyncio.TaskGroup() as group:
            first = group.create_task(tools.get_route("Origin", "Destination"))
            await started.wait()
            second = group.create_task(tools.get_route("Origin", "Destination", "car"))
            await asyncio.sleep(0)
            release.set()
        self.assertEqual(first.result()["distance_km"], second.result()["distance_km"])
        self.get.assert_awaited_once()

    async def test_render_reuses_route_but_creates_new_artifacts(self) -> None:
        await tools.get_route("Origin", "Destination", "taxi")
        self.get.return_value = httpx.Response(
            200, content=b"map-image", request=httpx.Request("GET", tools.AZ_STATIC_MAP_URL),
        )
        container = MagicMock()
        container.upload_blob = AsyncMock()
        with (
            patch.object(tools, "_blob_service", return_value=MagicMock()),
            patch.object(tools, "_get_container", AsyncMock(return_value=container)),
            patch.object(tools, "_readable_blob_url", side_effect=lambda c, name: name),
        ):
            first = await tools.render_route_map("Origin", "Destination", "car")
            second = await tools.render_route_map("Origin", "Destination", "car")
        self.assertNotIn("error", first)
        self.assertNotIn("error", second)
        self.assertNotEqual(first["recommendation_code"], second["recommendation_code"])
        self.assertEqual(container.upload_blob.await_count, 4)
        uploads = container.upload_blob.call_args_list
        for result, png, directions in (
            (first, uploads[0], uploads[1]), (second, uploads[2], uploads[3]),
        ):
            code = result["recommendation_code"]
            self.assertEqual(png.kwargs["name"], f"{code}.png")
            self.assertEqual(png.kwargs["data"], b"map-image")
            payload = json.loads(directions.kwargs["data"])
            self.assertEqual(payload["recommendation_code"], code)
            self.assertEqual(payload["map_image"], f"{code}.png")
        self.assertEqual(
            [call.args[0] for call in self.get.call_args_list],
            [tools.AZ_ROUTE_URL, tools.AZ_STATIC_MAP_URL],
        )

    async def test_map_cache_expiry_and_render_settings(self) -> None:
        self.get.return_value = httpx.Response(
            200, content=b"image", request=httpx.Request("GET", tools.AZ_STATIC_MAP_URL),
        )
        params = {"path": "route-a", "pins": "pins-a", "zoom": 12, "width": 900}
        async with httpx.AsyncClient() as client:
            await tools._get_static_map(client, params)
            self.clock.return_value = 1899.999
            self.assertEqual(await tools._get_static_map(client, params), b"image")
            self.get.assert_awaited_once()
            self.clock.return_value = 1900.0
            await tools._get_static_map(client, params)
            self.assertEqual(self.get.await_count, 2)
            for name, value in (("path", "route-b"), ("pins", "pins-b"), ("zoom", 13), ("width", 800)):
                await tools._get_static_map(client, {**params, name: value})
            self.assertEqual(self.get.await_count, 6)

    async def test_map_failures_are_reported_and_retried(self) -> None:
        await tools.get_route("Origin", "Destination")
        self.get.return_value = httpx.Response(
            429, text="rate limit", request=httpx.Request("GET", tools.AZ_STATIC_MAP_URL),
        )
        first = await tools.render_route_map("Origin", "Destination")
        self.assertEqual(first["error"], "Azure Maps static map HTTP 429")
        second = await tools.render_route_map("Origin", "Destination")
        self.assertEqual(second["error"], first["error"])
        self.get.side_effect = httpx.ConnectError("unavailable")
        third = await tools.render_route_map("Origin", "Destination")
        self.assertIn("static map request failed", third["error"])
        self.assertEqual(self.get.await_count, 4)

    async def test_oldest_route_is_evicted_when_full(self) -> None:
        with patch.object(tools, "_ROUTE_CACHE_MAX_ENTRIES", 2):
            for mode in ("car", "walking", "bike", "walking"):
                await tools.get_route("Origin", "Destination", mode)
            self.assertEqual(self.get.await_count, 3)
            await tools.get_route("Origin", "Destination", "car")
            self.assertEqual(self.get.await_count, 4)
            self.assertEqual(len(tools._route_cache), 2)


if __name__ == "__main__":
    unittest.main()
