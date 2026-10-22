# Guided player lessons

Follow these steps to build an agent that plays **Lost in the City**.
Players open **/<game-slug>/player** on the dashboard service. In **Guided
Mode**, the shared lessons below are rendered with the selected game's values.
In **Challenge Mode**, players receive four outcome-focused game missions
without the Guided Mode implementation walkthrough. The experience assumes a
prepared Windows workshop machine; the facilitator supplies credentials
privately.
For local service setup, see the [workshop overview](../docs/workshop-overview.md).

Guided Mode groups its nine detailed lessons into the same four named missions
as the game:

1. **Mission 1: Get Ready and Start the Game**
   - [Step into your workspace](guided/00_step_into_your_workspace.md)
   - [Get Azure OpenAI details from Microsoft Foundry](guided/01_get_azure_openai_details_from_foundry.md)
   - [Create a hello world agent](guided/02_create_hello_world_agent.md)
   - [Connect to the gaming MCP server](guided/03_connect_to_the_gaming_mcp_server.md)
   - [Add session logging](guided/05_add_session_logging.md)
2. **Mission 2: Use Agent42 to Travel**
   - [Test Agent42 transport specialist](guided/06_test_agent42_transport_specialist.md)
3. **Mission 3: Solve the Quest with Foundry IQ**
   - [Test the city guide agent](guided/07_test_the_city_guide_agent.md)
   - [Bring the specialist agents into the main agent](guided/08_bring_specialists_into_main_agent.md)
4. **Arrived: Complete the Game**
   - [Complete the final journey and review the lab](guided/09_lab_recap.md)

Challenge Mode follows the game itself:

1. [Mission 1: Get ready and start the game](challenge/00_mission_1_get_ready_and_start_the_game.md)
2. [Mission 2: Use Agent42 to travel](challenge/01_mission_2_use_agent42_to_travel.md)
3. [Mission 3: Solve the quest with Foundry IQ](challenge/02_mission_3_solve_the_quest_with_foundry_iq.md)
4. [Arrived: Complete the game](challenge/03_arrived_complete_the_game.md)

The canonical runnable sample is in
[src/agents/player/](../src/agents/player/). Steps 2, 3, and 5 build it incrementally;
Step 5 also supplies the logging helper, Steps 6–7 supply the specialist helpers,
and Step 8 supplies the complete **agent.py**. Keep those full copies and their
smaller integration snippets synchronized with the reference files. Step 0
introduces the Skillable environment, credential locations, and VS Code workspace.

## Per-game variables

Use these placeholders in lesson text or fenced code blocks:

| Placeholder | Value |
| --- | --- |
| `{{ game_name }}` / `{{ game_slug }}` | Game display name / URL slug |
| `{{ game_event }}` | Event name from the game record, or **this event** when unset |
| `{{ player_name }}` | Signed-in player's nickname, filled in by the browser |
| `{{ player_api_key }}` | Signed-in player's private API key, filled in by the browser. Shows `<copy-from-this-player-page>` until the player starts a game. |
| `{{ player_quest }}` | Name of the quest assigned to the signed-in player, filled in by the browser. Shows **your quest** until the player starts a game. |
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

When a play window is configured, the dashboard does not send lesson
navigation, lesson HTML, registration controls, or city-guide downloads outside
that window. The closed page shows **Player window is closed**. During the final
24 hours before opening it also shows a live **Enter the city in** countdown.

## Read-more overlays

To add a **Read more** overlay, link to `#more-<slug>` from a lesson, for
example `[Read more about MCP](#more-mcp)`, and add **more/&lt;slug&gt;.md**. Its
first line is the `# Title`; the rest is Markdown and supports the same
placeholders as lessons. The page shows the panel in a dialog and fails
explicitly if the file is missing. Existing panels are in [more/](more/).

Screenshots shared by Guided Mode are in [assets/](assets/). The admin and dashboard container builds
bundle these source lessons and images; redeploy those services after updating
content. Local development reads this directory directly. The old
[web index](index.html), [Skillable import](skillable.md), and
[export script](../scripts/sync-to-skillable.py) remain legacy exports and are
not the per-game player delivery path.
