# Lost in the City Gameplay

```text
                         LOST IN THE CITY
                    a workshop agent adventure

                               +-----+
                               | YOU |
                               +--+--+
                                  |
                                  | chat, choices, and questions
                                  v
+-------------------------------------------------------------------+
|                         GAME PLAY AGENT                           |
|                                                                   |
|  Reads the story, chooses tools, resumes the game, and keeps      |
|  the quest moving through the foggy streets of San Francisco.      |
+----+----------------------+----------------------+----------------+
     |                      |                      |
     | game actions         | movement advice      | city knowledge
     v                      v                      v
+----+----------------+  +--+----------------+  +--+----------------+
| GAME MCP SERVER     |  | AGENT42           |  | CITY GUIDE MCP    |
|                     |  |                  |  |                   |
| begin_session       |  | car, walking,     |  | neighborhood,     |
| resume_player       |  | or bike advice    |  | history, food,    |
| start_quest         |  | with route hints   |  | parks, culture    |
| submit answers      |  |                  |  | via search         |
+----+----------------+  +-------------------+  +--+----------------+
     |                                            |
     | story scenes, missions, scores             | retrieved context
     v                                            v
+-------------------------------------------------------------------+
|                         SESSION LOGS                              |
|                                                                   |
|  model input | tool calls | tool results | final responses        |
+-------------------------------------------------------------------+
```

The attendee first registers on the game's Player page and copies the private
API key into **GAME_API_KEY**. The agent sends it as a bearer token to the game
MCP server. The diagram shows the transport and retrieval paths; the player also
uses a vision-based Note Reader for secret-note missions.

## Gameplay Loop

```text
  1. Start or resume a player session
             |
             v
  2. Read the current mission from the game MCP server
             |
             v
  3. Decide what kind of mission it is
        +----+------------------+
        |                       |
        v                       v
  movement mission        guide question
        |                       |
        v                       v
  ask Agent42             ask City Guide
        |                       |
        +----------+------------+
                   |
                   v
  4. Submit the answer back to the game MCP server
                   |
                   v
  5. Continue until the final destination and leaderboard
```

## What Each Piece Does

| Piece | Job |
| --- | --- |
| You | Give the agent direction when the game asks for a player choice. |
| Game Play Agent | Orchestrates the quest and decides which tool or specialist to call. |
| Game MCP Server | Owns the game state, missions, prompts, scoring, and leaderboard. |
| Agent42 | Recommends transport for movement missions. |
| City Guide MCP | Exposes the knowledge base's retrieval and answer synthesis directly to the game agent. |
| Note Reader | Reads the secret note image, detects its language, and returns the password as structured output. |
| Player identity and progress | **GAME_API_KEY** identifies the player; Azure Tables stores progress so later runs can resume without a local memory file. |
| Session Logs | Show what the model saw, which tools it called, and what came back. |

## Tiny Quest Card

```text
+-------------------------------------------------------------+
| Current mission                                             |
|                                                             |
|  The city gives you a scene, a clue, or a destination.       |
|                                                             |
|  If it asks how to travel: ask Agent42.                      |
|  If it asks local knowledge: ask the City Guide.             |
|  If it asks for the password: read the secret note.         |
|  If it asks for final action: submit through the MCP server. |
+-------------------------------------------------------------+
```
