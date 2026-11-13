"""Verify shared geocoding cache behavior with mocked HTTP responses."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools


class GeocodeCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.enterContext(patch.object(
            tools, "_geocode_cache", tools._MemoryCache[tuple[float, float, str]](86400, 1024),
        ))
        self.clock = self.enterContext(patch.object(tools, "monotonic", return_value=100.0))
        self.enterContext(patch.object(tools, "_azure_maps_key", return_value="test-key"))
        self.enterContext(patch.object(tools, "GEOCODE_BIAS_POINT", None))
        self.response = httpx.Response(
            200, request=httpx.Request("GET", tools.AZ_GEOCODE_URL),
            json={"features": [{
                "geometry": {"coordinates": [-122.42, 37.77]},
                "properties": {"address": {"formattedAddress": "San Francisco"}},
            }]},
        )
        self.get = self.enterContext(patch.object(
            httpx.AsyncClient, "get", AsyncMock(return_value=self.response),
        ))
        self.client = await self.enterAsyncContext(httpx.AsyncClient())

    async def test_normalization_location_bias_and_expiry(self) -> None:
        first = await tools._geocode_azure(self.client, "San Francisco")
        self.assertEqual(first, (37.77, -122.42, "San Francisco"))
        self.clock.return_value = 86499.999
        self.assertEqual(
            await tools._geocode_azure(self.client, "  SAN   FRANCISCO "), first,
        )
        self.get.assert_awaited_once()
        self.clock.return_value = 86500.0
        await tools._geocode_azure(self.client, "San Francisco")
        self.assertEqual(self.get.await_count, 2)
        await tools._geocode_azure(self.client, "Berlin")
        with patch.object(tools, "GEOCODE_BIAS_POINT", "13.4,52.5"):
            await tools._geocode_azure(self.client, "San Francisco")
        self.assertEqual(self.get.await_count, 4)
        self.assertEqual(self.get.call_args.kwargs["params"]["coordinates"], "13.4,52.5")

    async def test_failures_are_not_cached(self) -> None:
        for response, error_type in (
            (httpx.Response(429, request=self.response.request), httpx.HTTPStatusError),
            (httpx.Response(200, text="invalid", request=self.response.request), ValueError),
            (httpx.Response(200, json={"features": []}, request=self.response.request), ValueError),
        ):
            with self.subTest(status=response.status_code, body=response.text):
                self.get.return_value = response
                with self.assertRaises(error_type):
                    await tools._geocode_azure(self.client, "San Francisco")
        self.get.return_value = self.response
        result = await tools._geocode_azure(self.client, "San Francisco")
        self.assertEqual(result[:2], (37.77, -122.42))
        self.assertEqual(self.get.await_count, 4)

    async def test_concurrent_requests_share_lookup(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def get(*args: object, **kwargs: object) -> httpx.Response:
            started.set()
            await release.wait()
            return self.response

        self.get.side_effect = get
        async with asyncio.TaskGroup() as group:
            first = group.create_task(tools._geocode_azure(self.client, "San Francisco"))
            await started.wait()
            second = group.create_task(tools._geocode_azure(self.client, "san francisco"))
            await asyncio.sleep(0)
            release.set()
        self.assertEqual(first.result(), second.result())
        self.get.assert_awaited_once()

    async def test_cache_size_is_bounded(self) -> None:
        with patch.object(tools, "_geocode_cache", tools._MemoryCache[tuple[float, float, str]](86400, 2)):
            for location in ("San Francisco", "Berlin", "London", "Berlin"):
                await tools._geocode_azure(self.client, location)
            self.assertEqual(self.get.await_count, 3)
            await tools._geocode_azure(self.client, "San Francisco")
            self.assertEqual(self.get.await_count, 4)


if __name__ == "__main__":
    unittest.main()
