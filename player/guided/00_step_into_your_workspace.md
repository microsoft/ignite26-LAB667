# Lost in the City Agent Workshop

Welcome to **{{ game_name }}**. Your facilitator sets the play window in
**{{ game_timezone }}**. You can read these instructions at any time; game actions
are available only during the scheduled window shown above.

> [!Hint] 🖥️ **In VS Code** — you'll do all of this lab's hands-on work in VS Code, except where a step tells you to switch to the browser.

## The Story

{{ game_story }}

You won't be navigating alone. In this workshop you'll build an AI **player
agent** that takes on the *Lost in the City* quest on your behalf. It will:

- Pick up missions from a game server and report back the answers.
- Phone a transport expert, **Agent42**, to decide whether to grab a taxi,
   hop on a bike, or hoof it — based on the weather, traffic, and route.
- Consult a **city guide** knowledge base to dig clues out of {{ game_city }}'s
   neighborhoods, history, food, and hidden corners.
- Remember who the player is between runs, and write a clear log of every
   model call, tool call, and decision it made.

Whoever's agent solves the most missions, fastest, takes the leaderboard.

## What You'll Build

A single Python agent, built with the **Microsoft Agent Framework**, that
combines four capabilities you'll add one step at a time:

- **MCP (Model Context Protocol)** — connect to the game server to start
   quests, submit answers, and progress through missions.
- **A2A (Agent-to-Agent)** — call Agent42 as a peer agent for
   weather-aware transport recommendations.
- **Knowledge retrieval** — query an Azure AI Search knowledge base over the
   {{ game_city }} city guide to answer the trivia-style missions.
- **Memory & logging** — remember the player ID between runs and capture
   every prompt, tool call, and response in a session log you can inspect.

By the end you'll have a working agent that plays the game end-to-end, and
you'll have seen how the framework, MCP, A2A, and retrieval fit together in
a real application instead of a toy demo.


## Login into the Machine
Use the prepared Windows 11 workshop machine provided by your facilitator.
Sign in with the credentials supplied to you privately. The public game
instructions do not contain passwords or access tokens.


## Step Into Your Workspace

On the Windows desktop, click the **Visual Studio Code** icon to open VS Code.

When VS Code starts, the **C:\workshop** folder should already be open. If that is
not the case:

1. Select **File > Open Folder**.
2. Choose the **C:\workshop** directory.

Open the integrated terminal with **Terminal > New Terminal** and confirm the
terminal is PowerShell and the prompt is inside **C:\workshop**.

The workshop environment already has the required Python packages installed. 

Verify the packages from the VS Code terminal:

```powershell
python -m pip check
python -c "from importlib.metadata import version; from agent_framework import Agent, MCPStreamableHTTPTool, SessionContext; from agent_framework.a2a import A2AAgent; from agent_framework.azure import AzureAISearchContextProvider; import dotenv; print('agent-framework', version('agent-framework')); print('agent-framework-a2a', version('agent-framework-a2a')); print('workshop packages ready')"
```

The player requires **agent-framework 1.19.0 or newer** and
**agent-framework-a2a 1.0.0b260918 or newer**. If the checks fail or report older
versions, update the workshop packages in this same terminal, then rerun both
checks:

```powershell
python -m pip install --upgrade --upgrade-strategy eager "agent-framework>=1.19.0" "agent-framework-a2a>=1.0.0b260918" python-dotenv
```

These are the same package requirements as the reference player's
**src/agents/player/requirements.txt**. The explicit A2A prerelease minimum
allows that integration without enabling prereleases for every package.

> [!Hint] The player and shared game server use separate Python environments.
> Do not install the game server's MCP 2 packages into the attendee environment:
> Agent Framework's supported MCP client communicates with the server over HTTP.
> The updated A2A player also needs the updated Agent42 service; ask your
> instructor if the transport test in Step 6 reports a protocol error.

The **C:\workshop** folder already has a **.env** file. You do not need to create a new
one. As you go through the workshop, open that file and add the values needed
for the current step.

## What You Learned

You confirmed the workshop workspace, terminal, installed packages, and **.env**
file are ready before building the agent.
