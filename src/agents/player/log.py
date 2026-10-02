"""Per-session conversation + tool I/O logging for the sample agent.

`open_session_log()` creates a fresh log file under `src/agents/player/logs/`.
`build_logging_middleware(path)` returns Agent Framework middlewares that
record every user/agent turn, every tool call, AND every chat call (which
includes whatever the context providers injected) into that file.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_framework import (
    AgentContext,
    AgentResponse,
    ChatContext,
    Content,
    FunctionInvocationContext,
    Message,
    agent_middleware,
    chat_middleware,
    function_middleware,
)
from pydantic import BaseModel

LOGS_DIR = Path(__file__).resolve().parent / "logs"


def open_session_log() -> Path:
    """Create a fresh log file for this chat session and return its path."""
    LOGS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = LOGS_DIR / f"session-{stamp}-{uuid.uuid4().hex[:6]}.log"
    path.write_text(f"# Session log started {datetime.now().isoformat()}\n\n", encoding="utf-8")
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
    def serialize(item: Any) -> Any:
        if isinstance(item, Content):
            return item.to_dict()
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        return str(item)

    return json.dumps(value, indent=2, default=serialize, ensure_ascii=False)


def _format_messages(messages: Sequence[Message]) -> str:
    parts: list[str] = []
    for message in messages:
        if message.text:
            parts.append(f"[{message.role}] {message.text}")
    return "\n".join(parts)


def build_logging_middleware(log_path: Path):
    """Return (agent_mw, chat_mw, function_mw) writing to log_path.

    - `agent_mw` logs user turns and final agent responses.
    - `chat_mw` logs the fully-resolved message list sent to the model
      (which includes anything context providers injected via `before_run`).
    - `function_mw` logs every tool call's inputs and outputs.
    """

    @agent_middleware
    async def log_agent(
        context: AgentContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        text = _format_messages(context.messages)
        if text:
            _append(log_path, "USER ->", _truncate(text))

        await call_next()

        if isinstance(context.result, AgentResponse) and context.result.text:
            _append(log_path, "AGENT <-", _truncate(context.result.text))

    @chat_middleware
    async def log_chat(
        context: ChatContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        instructions = (context.options or {}).get("instructions")
        if instructions:
            _append(log_path, "MODEL INSTRUCTIONS (post context providers) ->",
                    _truncate(_stringify(instructions)))
        text = _format_messages(context.messages)
        if text:
            _append(log_path, "MODEL INPUT (post context providers) ->", _truncate(text))
        await call_next()

    @function_middleware
    async def log_function(
        context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        fn_name = context.function.name
        _append(log_path, f"TOOL CALL  {fn_name}", _truncate(_stringify(context.arguments)))

        await call_next()

        _append(log_path, f"TOOL RESULT {fn_name}", _truncate(_stringify(context.result)))

    return log_agent, log_chat, log_function
