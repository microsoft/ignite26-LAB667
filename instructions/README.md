# Attendee instructions

Follow these steps to build an agent that plays **Lost in San Francisco**.
The existing walkthrough assumes a prepared Skillable Windows lab environment.
For local service setup, see the [workshop overview](../docs/workshop-overview.md).

1. [Step into your workspace](00_step_into_your_workspace.md)
2. [Get Azure OpenAI details from Microsoft Foundry](01_get_azure_openai_details_from_foundry.md)
3. [Create a hello world agent](02_create_hello_world_agent.md)
4. [Connect to the gaming MCP server](03_connect_to_the_gaming_mcp_server.md)
5. [Add memory for the player ID](04_add_memory_for_the_player_id.md)
6. [Add session logging](05_add_session_logging.md)
7. [Test Agent42 transport specialist](06_test_agent42_transport_specialist.md)
8. [Test the city guide agent](07_test_the_city_guide_agent.md)
9. [Bring the specialist agents into the main agent](08_bring_specialists_into_main_agent.md)
10. [Lab recap](09_lab_recap.md)

The canonical runnable sample is in
[src/agents/player/](../src/agents/player/). Steps 2–5 build it incrementally;
Step 5 also supplies the logging helper, Steps 6–7 supply the specialist helpers,
and Step 8 supplies the complete **agent.py**. Keep those full copies and their
smaller integration snippets synchronized with the reference files. Step 0
includes package compatibility checks and the player-only upgrade command.

Screenshots are in [assets/](assets/). The generated [web index](index.html) and
[Skillable import](skillable.md) are maintained by the
[export script](../scripts/sync-to-skillable.py). Existing hosted URLs are
preserved; moving the files does not publish them.
