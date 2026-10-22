# Step 4: Use The Player API Key

In this exercise, you connect the identity created on the Player page to every
game action without putting identity into prompts or tool arguments. The API
key is both the player identity and the authorization credential for the game
MCP server.

> [!Hint] 🖥️ **In the browser and VS Code** — copy the key from this page, then
> return to the existing **C:\workshop\.env** file in VS Code.

## Start your player

At the top of this Player page, enter a nickname and select **Start game**. The
page creates a private API key, stores it in this browser, and opens your live
timeline.

Use **Copy key** and add the value to the existing **C:\workshop\.env** file:

```env
GAME_API_KEY=<paste-your-private-player-key>
```

Do not add quotes around the value. Do not commit **.env**, paste the key into a
prompt, or include it in source code.

> [!Hint] The **Forget** button removes the key from this browser only. It does
> not delete the player from the game. Keep the key until the adventure is
> complete.

## Authenticate the MCP connection

Open **agent.py** and confirm the **MCPStreamableHTTPTool(...)** created in Step
3 includes the bearer header:

```python-notype
MCPStreamableHTTPTool(
    name="Gaming MCP Server",
    url=os.environ["GAME_MCP_URL"],
    static_headers={
        "Authorization": f"Bearer {os.environ['GAME_API_KEY']}",
    },
)
```

The header is sent by the HTTP client, not by the language model. The MCP tools
therefore know which player is acting without accepting a `player_id` argument.
The model should never see or repeat the key.

## Verify the authenticated session

Run the agent:

```powershell
python agent.py
```

The first MCP call is **begin_session()**. The server resolves the bearer key,
finds the nickname and assigned quest, and returns the current state. When you
say **START**, the agent calls **start_quest()** without identity parameters.

Return to this Player page after starting. Within a few seconds, the timeline
shows **Quest started**. Refreshing the page keeps the same player because the
browser remembers the key.

> **Checkpoint:** the agent greets the nickname from this page, the game starts
> without asking for a player ID, and the Player timeline shows both
> **Player ready** and **Quest started**.

## What You Learned

You replaced prompt-based player-ID memory with transport-level bearer
authentication. The browser, game MCP server, and later Agent42 calls now use
one private key to identify the same player and update one timeline.
