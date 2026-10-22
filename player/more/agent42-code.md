# The Agent42 code

**agent_agent42.py** connects to Agent42, turns it into a tool for your game
agent, and asks one test question. The numbers below follow the code from top
to bottom.

## Step by step

1. **Imports**: **httpx** is the HTTP client that carries the A2A messages.
   **A2AAgent** comes from the Microsoft Agent Framework A2A package and talks to
   a remote agent. **FunctionTool** is the type of the tool you create.
2. **build_agent42_agent()**: sets up the connection to Agent42.
   - **httpx.Timeout(...)**: Agent42 checks maps, weather, and traffic, so a
     reply can take a while. The code waits up to 60 seconds for an answer, and
     up to 10 seconds to connect. You can change the 60 with
     **AGENT42_TIMEOUT_SECONDS** in **.env**.
   - **httpx.AsyncClient(...)**: sends your API key as a bearer token with every
     request. Agent42 checks the same key as the game server, so it knows which
     player is asking and shows its advice on your Player page.
   - **A2AAgent(...)**: the remote agent itself. **url** is the address from
     **.env**, and **description** tells other agents what Agent42 is good at.
3. **build_agent42_tool()**: **as_tool(...)** wraps Agent42 as a tool called
   **ask_agent42**. Its description tells the model when to use it: to find the
   best way from one place to another. The model passes its question in the
   **question** argument.
4. **main()**: the test. It loads **.env**, opens the connection with
   **async with**, sends one question to Agent42, and prints the answer.
5. **asyncio.run(main())**: starts the test when you run the file directly.

## Why the connection uses async with

**async with build_agent42_agent() as agent42:** opens the connection to
Agent42 and closes it when the block ends, even if the request fails.
**build_agent42_tool()** reuses that open connection instead of opening a second
one.

## Try your own question

Change the **question** line in **main()** to ask about other places in
{{ game_city }}. Pick two places that are close enough for car, bike, and walking
to all make sense, within about 50 km of each other, so Agent42 has real
options to compare.

In the next mission, your game agent gets the **ask_agent42** tool and calls it
on its own for travel missions.
