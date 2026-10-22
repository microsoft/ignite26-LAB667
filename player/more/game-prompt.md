# The game play prompt

A prompt is a set of instructions for the model. The **{{ game_name }}** game
server shares one prompt, **game_play_prompt**. Your agent loads it with
**get_prompt** and uses it as its instructions. This is the text the server
returns:

```text
You are an agent that plays the game by using the available tools.
Show story text returned by game tools in full. Keep your own extra commentary short and plain.
Do not use markdown, bullet lists, tables, or code blocks. When a specialist tool returns advice
or an answer, show it plainly before continuing.
```

## What each line does

1. **"You are an agent that plays the game by using the available tools."**
   Gives the agent its job: play the game by calling the game tools.
2. **"Show story text returned by game tools in full."** The tools return the
   story of each scene. The agent reads it to the player and doesn't shorten it.
3. **"Keep your own extra commentary short and plain."** The story is the star.
   The agent adds only a little of its own.
4. **"Do not use markdown, bullet lists, tables, or code blocks."** The player
   reads the story as plain text, so the agent writes plain sentences.
5. **"When a specialist tool returns advice or an answer, show it plainly before
   continuing."** When a helper, such as Agent42 or the city guide, gives
   advice, the agent shows it to the player before it moves on.

## Why the server owns the prompt

The server keeps the prompt, so your agent doesn't hardcode the game rules. If
the game rules change, you don't have to change your code.

You can still add your own instructions later, for example to give the agent a
personality. In the next missions you also add the specialist tools that this
prompt refers to.
