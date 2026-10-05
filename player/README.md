# Guided player lessons

Follow these steps to build an agent that plays **Lost in the City**.
Players open **/<game-slug>/player** on the dashboard service. In **Guided
Mode**, the shared lessons below are rendered with the selected game's values.
In **Challenge Mode**, players receive a compact setup, goal, and success brief
without the step-by-step lessons. The experience assumes a prepared Windows
workshop machine; the facilitator supplies credentials privately.
For local service setup, see the [workshop overview](../docs/workshop-overview.md).

Both modes contain the same ten chapters:

1. [Step into your workspace](guided/00_step_into_your_workspace.md)
2. [Get Azure OpenAI details from Microsoft Foundry](guided/01_get_azure_openai_details_from_foundry.md)
3. [Create a hello world agent](guided/02_create_hello_world_agent.md)
4. [Connect to the gaming MCP server](guided/03_connect_to_the_gaming_mcp_server.md)
5. [Use the Player API key](guided/04_use_the_player_api_key.md)
6. [Add session logging](guided/05_add_session_logging.md)
7. [Test Agent42 transport specialist](guided/06_test_agent42_transport_specialist.md)
8. [Test the city guide agent](guided/07_test_the_city_guide_agent.md)
9. [Bring the specialist agents into the main agent](guided/08_bring_specialists_into_main_agent.md)
10. [Lab recap](guided/09_lab_recap.md)

The matching outcome-focused briefs live in [challenge/](challenge/).

The canonical runnable sample is in
[src/agents/player/](../src/agents/player/). Steps 2–5 build it incrementally;
Step 5 also supplies the logging helper, Steps 6–7 supply the specialist helpers,
and Step 8 supplies the complete **agent.py**. Keep those full copies and their
smaller integration snippets synchronized with the reference files. Step 0
includes package compatibility checks and the player-only upgrade command.

## Per-game variables

Use these placeholders in lesson text or fenced code blocks:

| Placeholder | Value |
| --- | --- |
| `{{ game_name }}` / `{{ game_slug }}` | Game display name / URL slug |
| `{{ game_city }}` | Published top-level `city` from the game's quest document |
| `{{ game_story }}` | Published top-level `story` from the game's quest document |
| `{{ game_mcp_url }}` | Configured MCP service base URL plus the game's MCP route |
| `{{ agent42_url }}` | Configured shared Agent42 base URL |
| `{{ game_start_date }}` / `{{ game_start_time }}` | Local start date / time |
| `{{ game_end_date }}` / `{{ game_end_time }}` | Local end date / time |
| `{{ game_timezone }}` | IANA timezone, such as Europe/Amsterdam |

Values are substituted as escaped text, not executable templates or Markdown.
Only the listed names are supported; unknown variables fail explicitly. Do not
put passwords, keys, or access tokens in these public lessons. Dates and times
display **Not scheduled** when the play window is unset. If a legacy document
has no `city`, the player experience uses the city retained in the game record. If a
legacy or unpublished game has no `story`, the player experience shows a generic
city-specific introduction.

Screenshots shared by Guided Mode are in [assets/](assets/). The admin and dashboard container builds
bundle these source lessons and images; redeploy those services after updating
content. Local development reads this directory directly. The old
[web index](index.html), [Skillable import](skillable.md), and
[export script](../scripts/sync-to-skillable.py) remain legacy exports and are
not the per-game player delivery path.
