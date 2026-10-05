# Step 5: Add Session Logging

In this exercise, you add local observability for model messages and tool calls.
This matters because an agent can make several decisions before producing one
answer, and a session log helps you understand that flow without exposing the
private Player API key.

> [!Hint] 🖥️ **In VS Code** — create the logging helper beside **agent.py** in
> **C:\workshop**.

## Create the logging helper

Create **C:\workshop\log.py** and paste the following code:

```python-notype
"""Per-session conversation and tool I/O logging."""

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
    LOGS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = LOGS_DIR / f"session-{stamp}-{uuid.uuid4().hex[:6]}.log"
    path.write_text(
        f"# Session log started {datetime.now().isoformat()}\n\n",
        encoding="utf-8",
    )
    return path


def _append(path: Path, header: str, body: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    with path.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {header}\n{body.rstrip()}\n\n")


def _truncate(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def _stringify(value: Any) -> str:
    def serialize(item: Any) -> Any:
        if isinstance(item, Content):
            return item.to_dict()
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        return str(item)

    return json.dumps(value, indent=2, default=serialize, ensure_ascii=False)


def _format_messages(messages: Sequence[Message]) -> str:
    return "\n".join(
        f"[{message.role}] {message.text}"
        for message in messages
        if message.text
    )


def build_logging_middleware(log_path: Path):
    @agent_middleware
    async def log_agent(
        context: AgentContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        text = _format_messages(context.messages)
        if text:
            _append(log_path, "USER ->", _truncate(text))
        await call_next()
        if isinstance(context.result, AgentResponse) and context.result.text:
            _append(log_path, "AGENT <-", _truncate(context.result.text))

    @chat_middleware
    async def log_chat(
        context: ChatContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        text = _format_messages(context.messages)
        if text:
            _append(log_path, "MODEL INPUT ->", _truncate(text))
        await call_next()

    @function_middleware
    async def log_function(
        context: FunctionInvocationContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        _append(
            log_path,
            f"TOOL CALL {context.function.name}",
            _truncate(_stringify(context.arguments)),
        )
        await call_next()
        _append(
            log_path,
            f"TOOL RESULT {context.function.name}",
            _truncate(_stringify(context.result)),
        )

    return log_agent, log_chat, log_function
```

The bearer key is attached by the MCP HTTP client and is not a tool argument,
so this middleware does not write it to the log.

## Add logging to the game agent

At the top of **agent.py**, import the helper:

```python
from log import build_logging_middleware, open_session_log
```

Inside **async with client.client:**, before opening the MCP connection, add:

```python-notype
log_path = open_session_log()
print(f"Session log: {log_path}")
agent_mw, chat_mw, function_mw = build_logging_middleware(log_path)
```

Then add the middleware to **Agent(...)**:

```python
middleware=[agent_mw, chat_mw, function_mw],
```

Run the agent:

```powershell
python agent.py
```

Open the newest file under **C:\workshop\logs**. It should contain the initial
user message, the model input, calls such as **begin_session** or
**start_quest**, their results, and the agent response.

> **Checkpoint:** a new session log exists, tool calls contain no `player_id`,
> and the file does not contain the value of **GAME_API_KEY**.

## What You Learned

You added middleware that records the agent decision flow while keeping
transport credentials outside prompts, tool arguments, and log files.
