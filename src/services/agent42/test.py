"""Quick A2A test client for Agent42.

Connects to a running Agent42 server over the A2A protocol and runs an
interactive chat loop in the terminal.

Usage:
    # in one shell:
    python server.py
    # in another:
    python test.py
"""
from __future__ import annotations

import asyncio
import os

from agent_framework.a2a import A2AAgent
from dotenv import load_dotenv

load_dotenv(override=True)


async def main() -> None:
    url = os.environ.get("AGENT42_URL", "http://localhost:8042")
    print(f"Connecting to Agent42 at {url} ...")

    agent42 = A2AAgent(
        name="Agent42",
        url=url,
    )

    session = agent42.create_session()
    print("Chat with Agent42 (type 'exit' or 'quit' to stop)\n")
    print("Example: I'm in The Mission and need to get to Hayes Valley. Car, walking, or bike?\n")
    print("Example: From: 88 Colin P Kelly Jr St, San Francisco to Moscone West, San Francisco, CA 94103, United States\n\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break
        try:
            response = await agent42.run(user_input, session=session)
        except Exception as exc:
            print(f"[error] {exc}\n")
            continue
        print(f"Agent42: {response.text}\n")


if __name__ == "__main__":
    asyncio.run(main())
