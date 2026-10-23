# City Guide Part 2: Connect the Knowledge Base to Your Agent

Your **san-francisco-cityguide** knowledge base is ready. In this part, you
build the **City Guide** specialist: a small agent that connects to the
knowledge base over MCP and answers questions from what it finds. You test it
on its own before you add it to your game agent.

Every Foundry IQ knowledge base is also an MCP server, so your agent connects
to it just like it connects to the game server.

## Copy the Search endpoint and key

Your agent connects to the knowledge base with the address and key of the Azure
AI Search service behind Foundry IQ.

1. In the Microsoft Foundry portal, open the connected Azure AI Search resource.
2. Copy the **endpoint**. It looks like
   **https://search-xxxx.search.windows.net**.
3. Copy the **key**.

## Add the knowledge base to configuration

Open the existing **.env** file, add these lines, and replace the two
placeholders with the endpoint and key you copied:

```env
CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1-mini
AZURE_SEARCH_ENDPOINT=<your Search endpoint>
AZURE_SEARCH_KNOWLEDGE_BASE_NAME=san-francisco-cityguide
AZURE_SEARCH_KEY=<your Search key>
```

The City Guide uses **gpt-4.1-mini**, a smaller and faster model than your game
agent. Short lookups don't need more.

## Create the City Guide tool

You create a new file, **agent_city_guide.py**, that turns the City Guide into a
tool your game agent can use. It does three things:

- **build_city_guide_agent()** creates a small agent that connects to your
  knowledge base over MCP and answers only from what it finds.
- **build_city_guide_tool()** wraps that agent as a tool called
  **ask_city_guide**. Later, your game agent calls this tool for city guide
  questions.
- **main()** asks the City Guide one test question, so you can check that it
  works before you add it to your game agent.

## Create agent_city_guide.py

1. In the VS Code Explorer, select the **C:\workshop** folder.
2. Select **New File** and name it **agent_city_guide.py**.
3. Copy the code below with the **Copy** button and paste it into
   **agent_city_guide.py**. VS Code saves the file automatically.

```python-notype
"""City guide specialist agent for San Francisco knowledge-base questions."""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from agent_framework import Agent, FunctionTool, MCPStreamableHTTPTool
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv


@asynccontextmanager
async def build_city_guide_agent() -> AsyncGenerator[Agent, None]:
	client = OpenAIChatClient(
		azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
		api_key=os.environ["AZURE_OPENAI_API_KEY"],
		model=(
			os.environ.get("CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME", "").strip()
			or os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]
		),
	)

	# Every Foundry IQ knowledge base is also an MCP server with one tool:
	# knowledge_base_retrieve.
	search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"].rstrip("/")
	knowledge_base = os.environ["AZURE_SEARCH_KNOWLEDGE_BASE_NAME"]
	city_guide_kb = MCPStreamableHTTPTool(
		name="City Guide Knowledge Base",
		url=f"{search_endpoint}/knowledgebases/{knowledge_base}/mcp?api-version=2026-08-01-preview",
		static_headers={"api-key": os.environ["AZURE_SEARCH_KEY"]},
	)

	async with client.client, city_guide_kb:
		yield Agent(
			client=client,
			name="San Francisco City Guide Agent",
			instructions=(
				"Answer San Francisco city guide questions. Always search the city guide "
				"knowledge base first and answer only from what it returns. "
				"Keep answers brief and return only the answer the game needs."
			),
			tools=[city_guide_kb],
		)


def build_city_guide_tool(guide_agent: Agent) -> FunctionTool:
	# The main game agent calls this tool only for city guide questions.
	return guide_agent.as_tool(
		name="ask_city_guide",
		description=(
			"Ask the San Francisco city guide a question. Use this only "
			"for city guide or local knowledge questions from the game."
		),
		arg_name="question",
		arg_description="The city guide question to answer.",
	)


async def main() -> None:
	load_dotenv(Path(__file__).with_name(".env"), override=True)

	question = "What neighborhood is Dolores Park in?"
	async with build_city_guide_agent() as guide_agent:
		response = await guide_agent.run(question)
		print(response.text)


if __name__ == "__main__":
	asyncio.run(main())
```

Not sure what the code above does? Click the button below for a step-by-step
explanation of each part.

[Explain the code](#more-city-guide-code)

## Test the City Guide

Run **agent_city_guide.py** from the VS Code terminal:

```powershell
python agent_city_guide.py
```

The City Guide searches the knowledge base and answers. The exact wording can
differ, but it looks like this:

```output-read
Dolores Park is in the Mission District.
```

## What You Learned

You connected a small agent to your Foundry IQ knowledge base over MCP,
turned that agent into a tool called **ask_city_guide**, and tested it on its
own: it searched the city guide and answered from what it found.

In the next mission, your game agent gets the **ask_city_guide** tool, next to
**ask_agent42**, and asks the City Guide on its own when a question comes up.
