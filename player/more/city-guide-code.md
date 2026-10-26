# The City Guide code

**agent_city_guide.py** prepares a direct MCP connection to your Foundry IQ
knowledge base. It returns the MCP tool itself, not a separate agent wrapped
as a tool.

## Step by step

1. **Imports**: **MCPStreamableHTTPTool** is the same MCP connection you used
   for the game server. **Agent** and **OpenAIChatClient** are used only by the
   standalone test.
2. **build_city_guide_tool()**: returns the MCP connection.
   - The URL combines your Search endpoint, knowledge base name, and API
     version.
   - The Search API key travels in the **api-key** header. You don't need
     a Foundry Toolbox or `az login`.
   - **allowed_tools** exposes only **knowledge_base_retrieve**.
   - **load_prompts=False** skips prompt discovery; this connection only
     needs the retrieval tool.
3. **main()**: loads **.env** and creates a model client using the existing
   **AZURE_OPENAI_DEPLOYMENT_NAME** value, **gpt-5.6-luna**. It opens the client
   and MCP connection with **async with**, checks that
   **knowledge_base_retrieve** is available, and creates a temporary test
   agent with that tool. The test agent asks where Dolores Park is and prints
   the answer. Both connections close when the test finishes or fails.
4. **asyncio.run(main())**: runs this question test when you run the file
   directly. Importing the file doesn't create an agent or open a connection.

## What happens when the game agent asks a question

The game agent calls **knowledge_base_retrieve** directly. Foundry IQ plans
the search, looks through the city guide, and synthesizes an answer using the
settings from part 1. The game agent uses that answer to complete the mission.

The temporary agent is only a test harness. In the game, there is no extra
City Guide agent or second model call around retrieval. The game agent decides
when to search, so it doesn't search on every turn.

## Test a question

Run **agent_city_guide.py** and check that the answer places Dolores Park in
**The Mission** or **Mission District**, matching the portal test in part 1.
Change the question in **main()** to test another city guide question.
In the next lesson, add the same MCP tool directly to your game agent.
