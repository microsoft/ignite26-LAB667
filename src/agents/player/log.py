"""Per-session conversation + tool I/O logging for the sample agent.

`open_session_log()` creates a fresh log file under `src/agents/player/logs/`.
`build_logging_middleware(path)` returns Agent Framework middlewares that
record every user/agent turn, every tool call, AND every chat call (which
includes whatever the context providers injected) into that file.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_framework import agent_middleware, chat_middleware, function_middleware

LOGS_DIR = Path(__file__).resolve().parent / "logs"


def open_session_log() -> Path:
    """Create a fresh log file for this chat session and return its path."""
    LOGS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = LOGS_DIR / f"session-{stamp}-{uuid.uuid4().hex[:6]}.log"
    path.write_text(f"# Session log started {datetime.now().isoformat()}\n\n")
    return path


def _append(path: Path, header: str, body: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {header}\n{body.rstrip()}\n\n")


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _stringify(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, default=str, ensure_ascii=False)
    except Exception:
        return repr(value)


def _format_messages(messages) -> str:
    parts: list[str] = []
    for m in messages or []:
        role = getattr(m, "role", "?")
        text = "".join(
            (getattr(c, "text", "") or "")
            for c in getattr(m, "contents", []) or []
        )
        if text:
            parts.append(f"[{role}] {text}")
    return "\n".join(parts)


def build_logging_middleware(log_path: Path):
    """Return (agent_mw, chat_mw, function_mw) writing to log_path.

    - `agent_mw` logs user turns and final agent responses.
    - `chat_mw` logs the fully-resolved message list sent to the model
      (which includes anything context providers injected via `before_run`).
    - `function_mw` logs every tool call's inputs and outputs.
    """

    @agent_middleware
    async def log_agent(context, call_next):
        text = _format_messages(context.messages)
        if text:
            _append(log_path, "USER ->", _truncate(text))

        await call_next()

        result = getattr(context, "result", None)
        out = getattr(result, "text", None)
        if out:
            _append(log_path, "AGENT <-", _truncate(out))

    @chat_middleware
    async def log_chat(context, call_next):
        text = _format_messages(context.messages)
        if text:
            _append(log_path, "MODEL INPUT (post context providers) ->", _truncate(text))
        await call_next()

    @function_middleware
    async def log_function(context, call_next):
        fn_name = getattr(getattr(context, "function", None), "name", "?")
        args = getattr(context, "arguments", {}) or {}
        _append(log_path, f"TOOL CALL  {fn_name}", _truncate(_stringify(args)))

        await call_next()

        result = getattr(context, "result", None)
        _append(log_path, f"TOOL RESULT {fn_name}", _truncate(_stringify(result)))

    return log_agent, log_chat, log_function
