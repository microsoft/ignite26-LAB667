"""Validation shared by draft saves, imports, and publication."""
from __future__ import annotations

import json
import math
from typing import Any


def validate_document(document: Any, *, publish: bool = False) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(document, dict) or not isinstance(document.get("quests"), list):
        return {"errors": ['The document must contain a "quests" array.'], "warnings": []}
    try:
        payload = json.dumps(document, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-16-le")) > 64000:
            errors.append("The quest document exceeds the 64 KB Azure Table property limit. Split it into separate games.")
    except (ValueError, TypeError):
        errors.append("The document contains invalid JSON values.")
    city = document.get("city")
    if city is not None and not isinstance(city, str):
        errors.append("Game city must be text.")
    elif isinstance(city, str) and len(city.strip()) > 100:
        errors.append("Game city must be 100 characters or fewer.")
    elif publish and (not isinstance(city, str) or not city.strip()):
        warnings.append("Add a game city to replace the legacy city in the player experience.")
    story = document.get("story")
    if story is not None and not isinstance(story, str):
        errors.append("Game story must be text.")
    elif publish and (not isinstance(story, str) or not story.strip()):
        warnings.append("Add a game story to replace the generic introduction in the player experience.")
    if publish and not document["quests"]:
        errors.append("Add at least one quest before publishing.")
    quest_ids: set[int] = set()

    def text(value: Any, label: str, required: bool = False) -> None:
        if not isinstance(value, str):
            errors.append(f"{label} must be text.")
        elif required and not value.strip():
            errors.append(f"{label} is required before publishing.")

    for index, quest in enumerate(document["quests"]):
        prefix = f"Quest {index + 1}"
        if not isinstance(quest, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        qid = quest.get("id")
        if type(qid) is not int or qid < 1 or qid in quest_ids:
            errors.append(f"{prefix} needs a unique positive integer ID.")
        else:
            quest_ids.add(qid)
        text(quest.get("name", ""), f"{prefix} name", publish)
        for name in ("begin", "end"):
            section = quest.get(name, {})
            if not isinstance(section, dict):
                errors.append(f"{prefix} {name} must be an object.")
            else:
                text(section.get("prompt", ""), f"{prefix} {name} prompt", publish)
                if "flavor" in section:
                    text(section["flavor"], f"{prefix} {name} atmosphere")
        missions = quest.get("missions")
        if not isinstance(missions, list):
            errors.append(f"{prefix} missions must be an array.")
            continue
        if publish and not missions:
            errors.append(f"{prefix} needs at least one mission before publishing.")
        mission_ids: set[str] = set()
        for mi, mission in enumerate(missions):
            label = f"{prefix}, mission {mi + 1}"
            if not isinstance(mission, dict):
                errors.append(f"{label} must be an object.")
                continue
            mid = mission.get("id")
            if not isinstance(mid, (str, int)) or isinstance(mid, bool) or not str(mid).strip() or str(mid) in mission_ids:
                errors.append(f"{label} needs a unique ID within its quest.")
            else:
                mission_ids.add(str(mid))
            kind = mission.get("type")
            if kind not in ("move", "question"):
                errors.append(f"{label} type must be move or question.")
            for field in ("arrival_prompt", "complete_prompt", "mission"):
                text(mission.get(field, ""), f"{label} {field}", publish and field == "mission" and kind == "question")
            answers = mission.get("valid_answers", [])
            if not isinstance(answers, list) or any(not isinstance(a, str) or not a.strip() for a in answers):
                errors.append(f"{label} accepted answers must be a list of nonempty text values.")
            elif publish and kind == "question" and not answers:
                errors.append(f"{label} needs at least one accepted answer.")
            for endpoint in ("start", "end"):
                address = mission.get(f"{endpoint}_address", "")
                text(address, f"{label} {endpoint} address", publish and kind == "move")
                lat, lng = mission.get(f"{endpoint}_lat"), mission.get(f"{endpoint}_lng")
                if lat is None and lng is None:
                    if address or kind == "move":
                        warnings.append(f"{label} {endpoint} has no map coordinates.")
                    continue
                if (
                    type(lat) not in (int, float) or type(lng) not in (int, float)
                    or not math.isfinite(lat) or not math.isfinite(lng)
                    or not -90 <= lat <= 90 or not -180 <= lng <= 180
                ):
                    errors.append(f"{label} {endpoint} needs valid latitude (-90..90) and longitude (-180..180).")
    return {"errors": errors, "warnings": warnings}
