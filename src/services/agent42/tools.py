"""Tools for Agent42: weather (Open-Meteo) and routing (Azure Maps).

Geocoding for BOTH weather and routing uses the Azure Maps Geocoding API and
works for any city in the world. Rendered route maps and turn-by-turn JSON
are uploaded to a public Azure Blob Storage container, and returned URLs point
directly at those public blobs.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import string
from collections.abc import Awaitable, Callable, Hashable
from copy import deepcopy
from time import monotonic
from typing import Any, Generic, TypeVar

import httpx
from agent_framework import tool
from azure.storage.blob import (
    ContentSettings,
    PublicAccess,
)
from azure.storage.blob.aio import BlobServiceClient, ContainerClient

_CacheValue = TypeVar("_CacheValue")


class _MemoryCache(Generic[_CacheValue]):
    def __init__(self, ttl_seconds: int, max_entries: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[Hashable, tuple[float, _CacheValue]] = {}
        self._lock = asyncio.Lock()

    async def get_or_load(
        self, key: Hashable, load: Callable[[], Awaitable[_CacheValue]],
    ) -> _CacheValue:
        cached = self._entries.get(key)
        if cached is not None and monotonic() < cached[0]:
            return cached[1]
        async with self._lock:
            cached = self._entries.get(key)
            if cached is not None and monotonic() < cached[0]:
                return cached[1]
            self._entries.pop(key, None)
            value = await load()
            if len(self._entries) >= self._max_entries:
                self._entries.pop(next(iter(self._entries)))
            self._entries[key] = (monotonic() + self._ttl_seconds, value)
            return value


# --- Open-Meteo (no API key required) ----------------------------------------

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_WEATHER_CACHE_TTL_SECONDS = 3600
_WEATHER_CACHE_MAX_ENTRIES = 1024
_weather_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_weather_cache_lock = asyncio.Lock()

# WMO weather codes -> short text. Subset; unknowns fall back to "unknown".
_WMO: dict[int, str] = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains",
    80: "light rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with light hail", 99: "thunderstorm with heavy hail",
}


@tool(description="Get the current weather for a location anywhere in the world (e.g. 'The Mission, San Francisco', 'Brandenburg Gate, Berlin'). Geocodes via Azure Maps and fetches conditions from Open-Meteo, cached for up to one hour. Returns temperature and feels-like temperature in Celsius and Fahrenheit, precipitation, wind, and a short condition string.")
async def get_current_weather(location: str) -> dict[str, Any]:
    key = " ".join(location.split()).casefold()
    cached = _weather_cache.get(key)
    if cached is not None and monotonic() < cached[0]:
        return cached[1].copy()

    # Recheck after waiting so simultaneous requests reuse the first lookup.
    async with _weather_cache_lock:
        cached = _weather_cache.get(key)
        if cached is not None and monotonic() < cached[0]:
            return cached[1].copy()
        _weather_cache.pop(key, None)
        weather = await _fetch_current_weather(location)
        if "error" not in weather:
            if len(_weather_cache) >= _WEATHER_CACHE_MAX_ENTRIES:
                _weather_cache.pop(next(iter(_weather_cache)))
            _weather_cache[key] = (
                monotonic() + _WEATHER_CACHE_TTL_SECONDS,
                weather.copy(),
            )
        return weather


async def _fetch_current_weather(location: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            lat, lon, label = await _geocode_azure(client, location)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            return {"error": f"geocoding failed: {exc}"}
        try:
            r = await client.get(
                FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_gusts_10m,relative_humidity_2m",
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "timezone": "auto",
                },
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"error": f"weather lookup failed: {exc}"}
    cur = data.get("current", {})
    code = int(cur.get("weather_code", -1))
    temperature_c = cur.get("temperature_2m")
    feels_like_c = cur.get("apparent_temperature")
    return {
        "location": label,
        "latitude": lat,
        "longitude": lon,
        "time": cur.get("time"),
        "temperature_c": temperature_c,
        "temperature_f": round(temperature_c * 9 / 5 + 32, 1) if temperature_c is not None else None,
        "feels_like_c": feels_like_c,
        "feels_like_f": round(feels_like_c * 9 / 5 + 32, 1) if feels_like_c is not None else None,
        "humidity_pct": cur.get("relative_humidity_2m"),
        "precipitation_mm": cur.get("precipitation"),
        "wind_speed_kmh": cur.get("wind_speed_10m"),
        "wind_gusts_kmh": cur.get("wind_gusts_10m"),
        "condition": _WMO.get(code, "unknown"),
        "weather_code": code,
    }


# --- Azure Maps Route + Geocoding -------------------------------------------
#
# Auth: shared-key via the `subscription-key` query parameter. (Entra ID is
# also supported by Azure Maps but the shared key keeps the workshop simple.)
#
# Geocoding uses the modern Azure Maps Geocoding API (`/geocode`), which
# returns GeoJSON and supersedes the legacy `/search/address/json` endpoint.

AZ_GEOCODE_URL = "https://atlas.microsoft.com/geocode"
AZ_GEOCODE_API_VERSION = "2025-01-01"
AZ_ROUTE_URL = "https://atlas.microsoft.com/route/directions/json"
_ROUTE_CACHE_TTL_SECONDS = 1800
_ROUTE_CACHE_MAX_ENTRIES = 1024
_route_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_route_cache_lock = asyncio.Lock()


async def _get_route_data(client: httpx.AsyncClient, params: dict[str, Any]) -> dict[str, Any]:
    key = (params["query"], params["travelMode"])
    cached = _route_cache.get(key)
    if cached is not None and monotonic() < cached[0]:
        return deepcopy(cached[1])

    async with _route_cache_lock:
        cached = _route_cache.get(key)
        if cached is not None and monotonic() < cached[0]:
            return deepcopy(cached[1])
        _route_cache.pop(key, None)
        try:
            response = await client.get(AZ_ROUTE_URL, params=params)
        except httpx.HTTPError as exc:
            return {"error": f"Azure Maps route request failed: {exc}"}
        if response.status_code >= 400:
            return {"error": f"Azure Maps HTTP {response.status_code}", "body": response.text[:400]}
        try:
            data = response.json()
        except ValueError as exc:
            return {"error": f"Azure Maps returned invalid JSON: {exc}"}
        if not data.get("routes"):
            return {"error": "no route found"}
        if len(_route_cache) >= _ROUTE_CACHE_MAX_ENTRIES:
            _route_cache.pop(next(iter(_route_cache)))
        _route_cache[key] = (monotonic() + _ROUTE_CACHE_TTL_SECONDS, deepcopy(data))
        return data

# Optional geocoding bias. Set AGENT42_GEOCODE_BIAS to a "lon,lat" string
# (e.g. "-122.4194,37.7749" for downtown San Francisco) to nudge short or
# ambiguous queries toward a specific city. Leave unset for global behavior.
GEOCODE_BIAS_POINT = os.environ.get("AGENT42_GEOCODE_BIAS", "").strip() or None
_geocode_cache = _MemoryCache[tuple[float, float, str]](ttl_seconds=86400, max_entries=1024)

# Logical mode names -> Azure Maps travelMode values. Azure Maps does not
# currently offer public-transit routing, so we map car / walking / bike
# cleanly to car / pedestrian / bicycle.
_MODE_TO_TRAVEL: dict[str, str] = {
    "driving": "car",
    "taxi": "car",
    "car": "car",
    "walking": "pedestrian",
    "pedestrian": "pedestrian",
    "bike": "bicycle",
    "bicycle": "bicycle",
}
_VALID_MODES = sorted(set(_MODE_TO_TRAVEL.keys()))


def _azure_maps_key() -> str:
    key = os.environ.get("AZURE_MAPS_KEY", "").strip()
    if not key:
        raise RuntimeError("AZURE_MAPS_KEY environment variable is not set.")
    return key


async def _geocode_azure(client: httpx.AsyncClient, query: str) -> tuple[float, float, str]:
    """Geocode a free-form query using the Azure Maps Geocoding API.

    Works globally. Pass a precise query (e.g. "Hayes Valley, San Francisco"
    or "Brandenburg Gate, Berlin") for best results; an optional bias point
    can be configured via the AGENT42_GEOCODE_BIAS env var.
    """
    key = (" ".join(query.split()).casefold(), GEOCODE_BIAS_POINT)
    return await _geocode_cache.get_or_load(key, lambda: _fetch_geocode_azure(client, query))


async def _fetch_geocode_azure(client: httpx.AsyncClient, query: str) -> tuple[float, float, str]:
    params: dict[str, Any] = {
        "api-version": AZ_GEOCODE_API_VERSION,
        "subscription-key": _azure_maps_key(),
        "query": query.strip(),
        "top": 1,
        "view": "Auto",
    }
    if GEOCODE_BIAS_POINT:
        params["coordinates"] = GEOCODE_BIAS_POINT

    r = await client.get(
        AZ_GEOCODE_URL,
        params=params,
        headers={"Accept": "application/geo+json"},
    )
    r.raise_for_status()
    data = r.json()
    features = data.get("features") or []
    if not features:
        raise ValueError(f"Azure Maps could not geocode: {query!r}")

    top = features[0]
    coords = (top.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        raise ValueError(f"Azure Maps returned no coordinates for: {query!r}")
    lon, lat = coords[0], coords[1]
    props = top.get("properties") or {}
    address = props.get("address") or {}
    label = (
        address.get("formattedAddress")
        or address.get("freeformAddress")
        or props.get("name")
        or query
    )
    return lat, lon, label


def _summarize_leg(leg: dict[str, Any]) -> dict[str, Any]:
    summary = leg.get("summary", {}) or {}
    return {
        "length_km": round((summary.get("lengthInMeters") or 0) / 1000.0, 3),
        "travel_time_seconds": summary.get("travelTimeInSeconds"),
        "traffic_delay_seconds": summary.get("trafficDelayInSeconds"),
        "departure_time": summary.get("departureTime"),
        "arrival_time": summary.get("arrivalTime"),
        "points": len(leg.get("points") or []),
    }


# Maximum straight-line distance (km) before we refuse to plan a local
# transport trip. Roughly 100 miles. Beyond this, "car / walking / bike"
# stops being a sensible question.
MAX_LOCAL_DISTANCE_KM = 161.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    import math

    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@tool(description=(
    "Get route information between two places using Azure Maps. "
    "mode must be one of: 'driving' / 'taxi' / 'car' (traffic-aware), "
    "'walking' / 'pedestrian', or 'bike' / 'bicycle'. "
    "Returns total distance, travel time, traffic delay (for driving), and per-leg summary. "
    "Route and traffic data are cached for up to 30 minutes; departure and arrival times reflect the original lookup. "
    "Note: Azure Maps does not currently provide public-transit routing. "
    "If the two places are more than ~100 miles apart in a straight line the "
    "tool refuses to plan a route and returns an error."
))
async def get_route(origin: str, destination: str, mode: str = "driving") -> dict[str, Any]:
    mode_key = (mode or "driving").strip().lower()
    if mode_key not in _MODE_TO_TRAVEL:
        return {"error": f"invalid mode {mode!r}; must be one of {_VALID_MODES}"}
    travel_mode = _MODE_TO_TRAVEL[mode_key]

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            o_lat, o_lon, o_label = await _geocode_azure(client, origin)
            d_lat, d_lon, d_label = await _geocode_azure(client, destination)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            return {"error": f"geocoding failed: {exc}"}

        straight_km = _haversine_km(o_lat, o_lon, d_lat, d_lon)
        if straight_km > MAX_LOCAL_DISTANCE_KM:
            return {
                "error": "too_far",
                "message": (
                    f"{o_label} and {d_label} are about "
                    f"{straight_km:.0f} km ({straight_km * 0.621:.0f} miles) apart in a "
                    "straight line. That's too far for car/walking/bike — "
                    "suggest a flight, train, or long-distance bus instead."
                ),
                "origin": {"query": origin, "resolved": o_label, "lat": o_lat, "lon": o_lon},
                "destination": {"query": destination, "resolved": d_label, "lat": d_lat, "lon": d_lon},
                "straight_line_distance_km": round(straight_km, 1),
                "straight_line_distance_miles": round(straight_km * 0.621, 1),
            }

        params: dict[str, Any] = {
            "api-version": "1.0",
            "subscription-key": _azure_maps_key(),
            "query": f"{o_lat},{o_lon}:{d_lat},{d_lon}",
            "travelMode": travel_mode,
            "instructionsType": "text",
        }
        if travel_mode == "car":
            # Real-time, traffic-aware routing. Azure Maps defaults departAt
            # to "now" when omitted (it does NOT accept the literal string
            # "now"), and `computeTravelTimeFor=all` enables the no-traffic,
            # historic-traffic, and live-incidents travel-time fields.
            params["traffic"] = "true"
            params["routeType"] = "fastest"
            params["computeTravelTimeFor"] = "all"

        data = await _get_route_data(client, params)
    if "error" in data:
        return data

    routes = data["routes"]
    route = routes[0]
    summary = route.get("summary", {}) or {}

    steps: list[dict[str, Any]] = []
    for g in (route.get("guidance") or {}).get("instructions", []) or []:
        steps.append({
            "text": g.get("message"),
            "point": g.get("point"),
            "travel_time_seconds": g.get("travelTimeInSeconds"),
        })

    return {
        "mode": mode_key,
        "travel_mode": travel_mode,
        "origin": {"query": origin, "resolved": o_label, "lat": o_lat, "lon": o_lon},
        "destination": {"query": destination, "resolved": d_label, "lat": d_lat, "lon": d_lon},
        "distance_km": round((summary.get("lengthInMeters") or 0) / 1000.0, 3),
        # travel_time_seconds already reflects real-time traffic when
        # travelMode=car and traffic=true.
        "travel_time_seconds": summary.get("travelTimeInSeconds"),
        "no_traffic_travel_time_seconds": summary.get("noTrafficTravelTimeInSeconds"),
        "historic_traffic_travel_time_seconds": summary.get("historicTrafficTravelTimeInSeconds"),
        "live_traffic_travel_time_seconds": summary.get("liveTrafficIncidentsTravelTimeInSeconds"),
        "traffic_delay_seconds": summary.get("trafficDelayInSeconds"),
        "traffic_length_meters": summary.get("trafficLengthInMeters"),
        "departure_time": summary.get("departureTime"),
        "arrival_time": summary.get("arrivalTime"),
        "legs": [_summarize_leg(leg) for leg in (route.get("legs") or [])],
        "steps": steps[:20],
    }


# --- Static map rendering ---------------------------------------------------

AZ_STATIC_MAP_URL = "https://atlas.microsoft.com/map/static"
AZ_STATIC_MAP_API_VERSION = "2024-04-01"
_static_map_cache = _MemoryCache[bytes](ttl_seconds=1800, max_entries=128)


async def _get_static_map(client: httpx.AsyncClient, params: dict[str, Any]) -> bytes:
    key = tuple(sorted((name, str(value)) for name, value in params.items() if name != "subscription-key"))

    async def fetch() -> bytes:
        response = await client.get(AZ_STATIC_MAP_URL, params=params)
        response.raise_for_status()
        return response.content

    return await _static_map_cache.get_or_load(key, fetch)

# --- Blob Storage for rendered maps + directions ----------------------------

BLOB_CONTAINER_NAME = os.environ.get("AGENT42_BLOB_CONTAINER", "agent42-routes")
_container_ready = False

# Alphabet used to generate the 15-character "recommendation code" that names
# the rendered map PNG and its directions JSON in blob storage.
_RECOMMENDATION_CODE_ALPHABET = string.ascii_lowercase + string.digits
_RECOMMENDATION_CODE_LENGTH = 15


def _new_recommendation_code() -> str:
    return "".join(
        secrets.choice(_RECOMMENDATION_CODE_ALPHABET)
        for _ in range(_RECOMMENDATION_CODE_LENGTH)
    )


def _blob_connection_string() -> str:
    cs = (
        os.environ.get("AGENT42_BLOB_CONNECTION_STRING")
        or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        or ""
    ).strip()
    if not cs:
        raise RuntimeError(
            "Set AGENT42_BLOB_CONNECTION_STRING (or AZURE_STORAGE_CONNECTION_STRING) "
            "to an Azure Storage connection string so rendered route maps can be "
            "uploaded."
        )
    return cs


def _readable_blob_url(container: ContainerClient, blob_name: str) -> str:
    return container.get_blob_client(blob_name).url


def _blob_service() -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(_blob_connection_string())


async def _get_container(svc: BlobServiceClient) -> ContainerClient:
    """Return the container client, creating it with public-blob access if needed.

    Caches a flag in-process so we only attempt the create on the first call.
    """
    global _container_ready
    container = svc.get_container_client(BLOB_CONTAINER_NAME)
    if not _container_ready:
        try:
            await container.create_container(public_access=PublicAccess.Blob)
        except Exception:
            # Either the container already exists, or the storage account
            # disallows public access. Either way, proceed and let the
            # upload surface any real error.
            pass
        _container_ready = True
    return container


def _downsample(points: list[dict[str, Any]], max_points: int = 95) -> list[dict[str, Any]]:
    """Downsample a polyline to fit within Azure Maps' 100-point path limit."""
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    out = [points[int(i * step)] for i in range(max_points)]
    # Always keep the final point so the line reaches the destination.
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def _center_and_zoom(points: list[dict[str, Any]], width: int, height: int, pad: float = 1.8) -> tuple[float, float, int]:
    """Compute a Web-Mercator center + zoom that fits the polyline.

    `pad` > 1 leaves breathing room around the route. We also subtract one
    zoom level so the map shows more context around the line instead of
    cropping in tight to it.
    """
    import math

    lats = [p["latitude"] for p in points]
    lons = [p["longitude"] for p in points]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2

    # World width at zoom 0 is 256 px = 360°. Each zoom doubles.
    lon_span = max(max_lon - min_lon, 1e-4) * pad
    # Latitude span needs Mercator correction at this latitude.
    lat_rad = math.radians(center_lat)
    lat_span_mercator = max(max_lat - min_lat, 1e-4) * pad / math.cos(lat_rad)

    zoom_lon = math.log2(width * 360.0 / (256.0 * lon_span))
    zoom_lat = math.log2(height * 360.0 / (256.0 * lat_span_mercator))
    # Pull back one extra zoom level so the route doesn't fill the entire frame.
    zoom = int(max(1, min(19, math.floor(min(zoom_lon, zoom_lat)) - 1)))
    return center_lat, center_lon, zoom


@tool(description=(
    "Render a static PNG map of a route between two places and upload it to "
    "Azure Blob Storage along with a turn-by-turn directions JSON. Use this "
    "AFTER you've picked your recommendation; pass the same origin, "
    "destination, and mode. Uses route and traffic data cached for up to 30 minutes. "
    "Returns `url` (PNG), `directions_url` (JSON), and "
    "`recommendation_code` (a 15-character id shared by both blobs)."
))
async def render_route_map(origin: str, destination: str, mode: str = "car") -> dict[str, Any]:
    mode_key = (mode or "car").strip().lower()
    if mode_key not in _MODE_TO_TRAVEL:
        return {"error": f"invalid mode {mode!r}; must be one of {_VALID_MODES}"}
    travel_mode = _MODE_TO_TRAVEL[mode_key]

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            o_lat, o_lon, _ = await _geocode_azure(client, origin)
            d_lat, d_lon, _ = await _geocode_azure(client, destination)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            return {"error": f"geocoding failed: {exc}"}

        straight_km = _haversine_km(o_lat, o_lon, d_lat, d_lon)
        if straight_km > MAX_LOCAL_DISTANCE_KM:
            return {
                "error": "too_far",
                "message": (
                    f"{origin} and {destination} are about {straight_km:.0f} km "
                    f"({straight_km * 0.621:.0f} miles) apart — refusing to draw "
                    "a local-transport map."
                ),
                "straight_line_distance_km": round(straight_km, 1),
            }

        route_params: dict[str, Any] = {
            "api-version": "1.0",
            "subscription-key": _azure_maps_key(),
            "query": f"{o_lat},{o_lon}:{d_lat},{d_lon}",
            "travelMode": travel_mode,
            "instructionsType": "text",
        }
        if travel_mode == "car":
            route_params["traffic"] = "true"
            route_params["routeType"] = "fastest"
            route_params["computeTravelTimeFor"] = "all"

        route_data = await _get_route_data(client, route_params)
        if "error" in route_data:
            return route_data
        routes = route_data["routes"]
        all_points: list[dict[str, Any]] = []
        for leg in routes[0].get("legs", []) or []:
            all_points.extend(leg.get("points") or [])
        if len(all_points) < 2:
            return {"error": "route had no polyline points"}

        pts = _downsample(all_points)
        width, height = 900, 700
        center_lat, center_lon, zoom = _center_and_zoom(pts, width, height)

        # Azure Maps static `path` expects "lon lat" pairs, pipe-separated.
        path_pts = "|".join(f"{p['longitude']:.5f} {p['latitude']:.5f}" for p in pts)
        # Per-mode line color: blue car, green walking, orange bike.
        color = {"car": "0066FFAA", "pedestrian": "22AA22AA", "bicycle": "FF8800AA"}[travel_mode]
        path_param = f"lc{color}|lw6||{path_pts}"
        pins_param = (
            f"default|coFF3333||{o_lon:.5f} {o_lat:.5f}|{d_lon:.5f} {d_lat:.5f}"
        )

        map_params = {
            "api-version": AZ_STATIC_MAP_API_VERSION,
            "subscription-key": _azure_maps_key(),
            "tilesetId": "microsoft.base.road",
            "center": f"{center_lon},{center_lat}",
            "zoom": zoom,
            "width": width,
            "height": height,
            "path": path_param,
            "pins": pins_param,
        }
        try:
            image_bytes = await _get_static_map(client, map_params)
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"Azure Maps static map HTTP {exc.response.status_code}",
                "body": exc.response.text[:300],
            }
        except httpx.HTTPError as exc:
            return {"error": f"Azure Maps static map request failed: {exc}"}

    # Build the turn-by-turn directions JSON for the recommended mode.
    summary = (routes[0].get("summary") or {}) if routes else {}
    steps: list[dict[str, Any]] = []
    for g in (routes[0].get("guidance") or {}).get("instructions", []) or []:
        steps.append({
            "text": g.get("message"),
            "point": g.get("point"),
            "travel_time_seconds": g.get("travelTimeInSeconds"),
        })

    # Upload both blobs to the public container. The 15-character
    # "recommendation code" is the shared stem of the PNG and JSON blobs
    # and is returned to the caller for later lookup.
    recommendation_code = _new_recommendation_code()
    png_blob = f"{recommendation_code}.png"
    json_blob = f"{recommendation_code}.json"

    directions_payload = {
        "recommendation_code": recommendation_code,
        "mode": mode_key,
        "travel_mode": travel_mode,
        "origin": {"query": origin, "lat": o_lat, "lon": o_lon},
        "destination": {"query": destination, "lat": d_lat, "lon": d_lon},
        "straight_line_distance_km": round(straight_km, 3),
        "distance_km": round((summary.get("lengthInMeters") or 0) / 1000.0, 3),
        "travel_time_seconds": summary.get("travelTimeInSeconds"),
        "traffic_delay_seconds": summary.get("trafficDelayInSeconds"),
        "departure_time": summary.get("departureTime"),
        "arrival_time": summary.get("arrivalTime"),
        "steps": steps,
        "map_image": png_blob,
        "raw_route": route_data,
    }
    json_bytes = json.dumps(directions_payload, indent=2).encode("utf-8")

    try:
        async with _blob_service() as svc:
            container = await _get_container(svc)
            await container.upload_blob(
                name=png_blob,
                data=image_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="image/png"),
            )
            png_url = _readable_blob_url(container, png_blob)
            await container.upload_blob(
                name=json_blob,
                data=json_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="application/json"),
            )
            directions_url = _readable_blob_url(container, json_blob)
    except Exception as exc:
        return {"error": f"blob upload failed: {exc}"}

    return {
        "recommendation_code": recommendation_code,
        "mode": mode_key,
        "origin": origin,
        "destination": destination,
        "url": png_url,
        "directions_url": directions_url,
        "size_bytes": len(image_bytes),
    }
