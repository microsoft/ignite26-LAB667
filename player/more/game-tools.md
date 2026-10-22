# The game tools

The **{{ game_name }}** game server shares seven tools and one prompt through
MCP. Your agent finds them when it connects, and the model decides when to call
each one. Every tool acts for the player that your API key identifies.

## Start or continue

- **begin_session**: the first call of every conversation. It greets the player
  and reports where they are: ready to start, a quest in progress, finished, or
  abandoned. It also tells the agent what to ask the player next.
- **start_quest**: begins the player's quest and returns the opening scene and
  the first mission.
- **resume_player**: continues a quest that is already in progress. It returns
  the scene and the current mission again.

## Play the missions

- **submit_mission_answer**: sends the answer for the current mission and moves
  the quest forward when it is correct.
  - **answer**: the answer to give. For a travel mission, this is the transport
    choice: car, walking, or bike. For a question mission, it is the answer you
    found in the city guide.
  - **route_ref**: an optional private route reference for travel missions. The
    agent never mentions it to the player.

## Check progress

- **get_player_status**: returns the player's name, quest, current mission,
  answer attempts, failed attempts, and completed missions, plus the score in
  Competitive Mode. It never reveals secret answers.
- **get_leaderboard**: returns the top 10 players by score. It only works in
  games with Competitive Mode turned on.

## Give up

- **abandon_quest**: stops the current quest. It takes an optional **reason**.
  The player starts a new game from the Player page to try again.

## The prompt

- **game_play_prompt**: not a tool but a set of instructions. The server owns
  it, and your agent loads it as its instructions so it follows the current
  rules of the game. You load it with **get_prompt** in this lesson.

## How the agent uses them

A typical run goes in this order: **begin_session**, then **start_quest**, then
**submit_mission_answer** for each mission, and **get_player_status** whenever
the player asks how they are doing. The tool results tell the model what to do
next, so you don't have to write the game flow yourself.
