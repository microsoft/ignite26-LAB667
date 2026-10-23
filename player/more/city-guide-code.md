# The City Guide code

**agent_city_guide.py** connects a small agent to your Foundry IQ knowledge
base, turns that agent into a tool for your game agent, and asks one test
question. The numbers below follow the code from top to bottom.

## Step by step

1. **Imports**: **MCPStreamableHTTPTool** is the same MCP connection you used
   for the game server. **asynccontextmanager** lets the builder open
   connections and close them again when you're done.
2. **build_city_guide_agent()**: sets up the City Guide specialist.
   - **OpenAIChatClient(...)**: the model for the specialist. It uses
     **CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME** from **.env**, a smaller model
     than your game agent. If that line is empty, it falls back to your main
     model.
   - **MCPStreamableHTTPTool(...)**: the connection to your knowledge base.
     Every Foundry IQ knowledge base is also an MCP server, and its address is
     built from your Search endpoint and the knowledge base name. The Search
     key travels in the **api-key** header.
   - **Agent(...)**: the specialist itself. Its instructions tell it to search
     the knowledge base first and answer only from what it finds, briefly.
3. **build_city_guide_tool()**: **as_tool(...)** wraps the specialist as a tool
   called **ask_city_guide**. Its description tells the game agent to use it
   only for city guide questions. The question goes in the **question**
   argument.
4. **main()**: the test. It loads **.env**, opens the specialist with
   **async with**, asks where Dolores Park is, and prints the answer.
5. **asyncio.run(main())**: starts the test when you run the file directly.

## What happens when the specialist answers

The specialist calls **knowledge_base_retrieve** with your question. Foundry IQ
plans the search, looks through the city guide, and sends back the passages
that match. The specialist reads them and writes a short answer.

## Why the specialist is a separate agent

Searching the city guide costs tokens. Because the knowledge base sits behind
its own agent, your game agent only pays for a search when it asks
**ask_city_guide**, not on every turn.

## Try your own question

Change the **question** line in **main()** to ask something else from the
{{ game_city }} city guide, such as a neighborhood, a park, or a local food
favorite.
