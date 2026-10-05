# Persist the Player Identity

Your goal is to make repeated runs resume the same player instead of registering a new one every time. This matters because the quest spans multiple missions and the server associates progress with the player ID.

## Challenge

Add durable local memory for the player ID. The solution must distinguish first-run registration from later-run resume behavior, tolerate a missing memory file, and avoid silently discarding corrupt state.

## Expected outcome

- The first run stores the player ID returned by the game server.
- Later runs reuse that ID and resume the existing quest.
- Memory is scoped to the player application and stored outside source code.
- Invalid memory produces a clear recovery path.
- The agent does not create duplicate players during normal repeated runs.

## Completion check

Two consecutive runs report the same player ID, and the second run continues from the state created by the first.
