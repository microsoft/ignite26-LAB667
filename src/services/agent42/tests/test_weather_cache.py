"""Exercise weather caching without calling Maps or Open-Meteo."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools


class WeatherCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        tools._weather_cache.clear()
        self.addCleanup(tools._weather_cache.clear)
        self.enterContext(patch.object(tools, "_weather_cache_lock", asyncio.Lock()))
        self.clock = self.enterContext(patch.object(tools, "monotonic", return_value=100.0))
        self.geocode = self.enterContext(patch.object(
            tools, "_geocode_azure",
            AsyncMock(return_value=(37.77, -122.42, "San Francisco")),
        ))
        self.get = self.enterContext(patch.object(
            httpx.AsyncClient, "get",
            AsyncMock(return_value=httpx.Response(
                200,
                request=httpx.Request("GET", tools.FORECAST_URL),
                json={"current": {
                    "time": "2026-11-13T14:00",
                    "temperature_2m": 14,
                    "apparent_temperature": 12.5,
                    "weather_code": 61,
                }},
            )),
        ))

    async def test_reuses_normalized_location_without_sharing_mutations(self) -> None:
        first = await tools.get_current_weather("San Francisco")
        self.assertEqual(first["temperature_c"], 14)
        self.assertEqual(first["temperature_f"], 57.2)
        self.assertEqual(first["feels_like_c"], 12.5)
        self.assertEqual(first["feels_like_f"], 54.5)
        self.assertEqual(first["condition"], "light rain")
        first["temperature_c"] = 99
        second = await tools.get_current_weather("  SAN   FRANCISCO  ")
        self.assertEqual(second["temperature_c"], 14)
        self.assertEqual(second["temperature_f"], 57.2)
        self.assertEqual(second["feels_like_f"], 54.5)
        second["temperature_c"] = 98
        third = await tools.get_current_weather("san francisco")
        self.assertEqual(third["temperature_c"], 14)
        self.get.assert_awaited_once()
        self.geocode.assert_awaited_once()
        await tools.get_current_weather("Berlin")
        self.assertEqual(self.get.await_count, 2)

    async def test_temperature_conversion_handles_zero_negative_and_missing_values(self) -> None:
        for current, expected in (
            ({"temperature_2m": 0, "apparent_temperature": -10.2}, (0, 32.0, -10.2, 13.6)),
            ({"temperature_2m": None, "apparent_temperature": None}, (None, None, None, None)),
            ({}, (None, None, None, None)),
        ):
            with self.subTest(current=current):
                tools._weather_cache.clear()
                self.get.return_value = httpx.Response(
                    200,
                    request=httpx.Request("GET", tools.FORECAST_URL),
                    json={"current": current},
                )
                result = await tools.get_current_weather("San Francisco")
                self.assertEqual(
                    tuple(result[key] for key in (
                        "temperature_c", "temperature_f", "feels_like_c", "feels_like_f",
                    )),
                    expected,
                )
                self.assertEqual(self.get.call_args.kwargs["params"]["temperature_unit"], "celsius")

    async def test_expires_exactly_one_hour_after_fetch(self) -> None:
        await tools.get_current_weather("San Francisco")
        self.clock.return_value = 3699.999
        await tools.get_current_weather("San Francisco")
        self.get.assert_awaited_once()
        self.clock.return_value = 3700.0
        await tools.get_current_weather("San Francisco")
        self.assertEqual(self.get.await_count, 2)
        self.assertEqual(self.geocode.await_count, 2)

    async def test_failed_refresh_is_not_cached_or_replaced_with_stale_weather(self) -> None:
        await tools.get_current_weather("San Francisco")
        self.clock.return_value = 3700.0
        self.get.side_effect = httpx.ConnectError("unavailable")
        failed = await tools.get_current_weather("San Francisco")
        self.assertIn("weather lookup failed", failed["error"])
        self.get.side_effect = None
        recovered = await tools.get_current_weather("San Francisco")
        self.assertEqual(recovered["temperature_c"], 14)
        self.assertEqual(self.get.await_count, 3)

    async def test_geocoding_errors_are_not_cached(self) -> None:
        self.geocode.side_effect = ValueError("location not found")
        failed = await tools.get_current_weather("San Francisco")
        self.assertIn("geocoding failed", failed["error"])
        self.get.assert_not_awaited()
        self.geocode.side_effect = None
        recovered = await tools.get_current_weather("San Francisco")
        self.assertEqual(recovered["temperature_c"], 14)
        self.assertEqual(self.geocode.await_count, 2)

    async def test_concurrent_requests_share_one_lookup(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def geocode(*args: object) -> tuple[float, float, str]:
            started.set()
            await release.wait()
            return 37.77, -122.42, "San Francisco"

        self.geocode.side_effect = geocode
        async with asyncio.TaskGroup() as group:
            first = group.create_task(tools.get_current_weather("San Francisco"))
            await started.wait()
            second = group.create_task(tools.get_current_weather("San Francisco"))
            await asyncio.sleep(0)
            release.set()
        self.assertEqual(first.result(), second.result())
        self.get.assert_awaited_once()
        self.geocode.assert_awaited_once()

    async def test_cache_evicts_oldest_location_when_full(self) -> None:
        with patch.object(tools, "_WEATHER_CACHE_MAX_ENTRIES", 2):
            for location in ("San Francisco", "Berlin", "London", "Berlin"):
                await tools.get_current_weather(location)
            self.assertEqual(self.get.await_count, 3)
            await tools.get_current_weather("San Francisco")
            self.assertEqual(self.get.await_count, 4)
            self.assertEqual(len(tools._weather_cache), 2)


if __name__ == "__main__":
    unittest.main()
