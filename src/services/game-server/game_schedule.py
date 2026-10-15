"""Game-local schedule input, UTC persistence, and play-window checks."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, model_validator


def _to_utc(value: datetime, zone: ZoneInfo) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    candidates = {
        value.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        for fold in (0, 1)
        if value.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        .astimezone(zone).replace(tzinfo=None) == value
    }
    if not candidates:
        raise ValueError("This local time does not exist because the clocks change. Choose another time.")
    if len(candidates) != 1:
        raise ValueError("This local time occurs twice because the clocks change. Choose an unambiguous time or supply an explicit UTC offset through the API.")
    return candidates.pop()


class GameSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: str = "UTC"
    player_mode: Literal["guided", "challenge"] = "guided"
    competitive_mode: bool = False

    @model_validator(mode="after")
    def validate_window(self) -> GameSchedule:
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Choose a valid IANA timezone, such as Europe/Amsterdam or America/Los_Angeles.") from exc
        if (self.starts_at is None) != (self.ends_at is None):
            raise ValueError("Provide both start and end dates/times, or leave both empty for unrestricted play.")
        if self.starts_at is not None and self.ends_at is not None:
            self.starts_at = _to_utc(self.starts_at, zone)
            self.ends_at = _to_utc(self.ends_at, zone)
            if self.ends_at <= self.starts_at:
                raise ValueError("The end must be after the start.")
        return self

    def storage_fields(self) -> dict[str, str | bool]:
        return {
            "starts_at": self.starts_at.isoformat() if self.starts_at else "",
            "ends_at": self.ends_at.isoformat() if self.ends_at else "",
            "timezone": self.timezone,
            "player_mode": self.player_mode,
            "competitive_mode": self.competitive_mode,
        }


def schedule_for(game: dict[str, Any]) -> GameSchedule:
    return GameSchedule(
        starts_at=game.get("starts_at") or None,
        ends_at=game.get("ends_at") or None,
        timezone=game.get("timezone", "UTC"),
        player_mode=game.get("player_mode", "guided"),
        competitive_mode=bool(game.get("competitive_mode", False)),
    )


def local_fields(game: dict[str, Any]) -> dict[str, str | bool]:
    schedule = schedule_for(game)
    zone = ZoneInfo(schedule.timezone)
    return {
        "starts_at": schedule.starts_at.astimezone(zone).strftime("%Y-%m-%dT%H:%M:%S") if schedule.starts_at else "",
        "ends_at": schedule.ends_at.astimezone(zone).strftime("%Y-%m-%dT%H:%M:%S") if schedule.ends_at else "",
        "timezone": schedule.timezone,
        "player_mode": schedule.player_mode,
        "competitive_mode": schedule.competitive_mode,
    }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def game_availability(game: dict[str, Any]) -> dict[str, Any]:
    schedule = schedule_for(game)
    if schedule.starts_at is None or schedule.ends_at is None:
        return {"state": "open", "message": "No play window is set. Gameplay is unrestricted."}
    now = utcnow()
    local = local_fields(game)
    window = f"{local['starts_at'].replace('T', ' ')} to {local['ends_at'].replace('T', ' ')} ({schedule.timezone})"
    if now < schedule.starts_at:
        return {
            "state": "scheduled",
            "message": f"This game has not started. Play window: {window}.",
            "starts_at": schedule.starts_at.isoformat(),
            "seconds_until_start": math.ceil((schedule.starts_at - now).total_seconds()),
        }
    if now >= schedule.ends_at:
        return {"state": "ended", "message": f"This game has ended. Play window: {window}."}
    return {"state": "open", "message": f"This game is open. Play window: {window}."}
