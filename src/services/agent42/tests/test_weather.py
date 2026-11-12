"""Tests for Agent42's weather tool."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools


class WeatherTests(unittest.IsolatedAsyncioTestCase):
    async def test_weather_uses_fahrenheit(self) -> None:
        class Response:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict:
                return {
                    "current": {
                        "temperature_2m": 68,
                        "apparent_temperature": 66,
                        "weather_code": 0,
                    }
                }

        class Client:
            async def __aenter__(self) -> Client:
                return self

            async def __aexit__(self, *args: object) -> None:
                pass

            async def get(self, url: str, *, params: dict) -> Response:
                self.params = params
                return Response()

        client = Client()
        with patch.object(
            tools, "_geocode_azure", new=AsyncMock(return_value=(37.77, -122.42, "San Francisco"))
        ), patch.object(tools.httpx, "AsyncClient", return_value=client):
            result = await tools.get_current_weather.invoke(location="San Francisco")
            weather = json.loads(result[0].text)

        self.assertEqual(client.params["temperature_unit"], "fahrenheit")
        self.assertEqual(weather["temperature_f"], 68)
        self.assertEqual(weather["feels_like_f"], 66)
        self.assertNotIn("temperature_c", weather)
        self.assertNotIn("feels_like_c", weather)


if __name__ == "__main__":
    unittest.main()
