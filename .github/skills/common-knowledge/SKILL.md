---
name: common-knowledge
description: "Use when: editing workshop docs, README content, lab instructions, product names, setup steps, or terminology in this repository. Remembers common repository facts and preferred wording."
---

# Common Repository Knowledge

Use these facts when editing documentation, workshop steps, README content, or generated workshop materials.

## Product Names

- Use **Microsoft Foundry**.
- Do not write **Azure AI Foundry** or **Azure Foundry**.
- **Azure OpenAI** is still valid when referring to the model endpoint, deployment, or API key.
- **Azure AI Search** is valid when referring to the search service or knowledge base backing retrieval.
- **Microsoft Agent Framework**, **MCP**, and **A2A** are valid workshop terms.
- **Agent42** is the transport expert agent.
- **Lost in the City** is the workshop/game family name.

## Lab Environment

- The attendee works inside the Windows 11 lab VM.
- The workshop folder on the lab VM is **C:\workshop**.
- Tell attendees to open VS Code by clicking the **Visual Studio Code** icon on the Windows desktop.
- The **C:\workshop** folder should already be open in VS Code.
- The terminal should be PowerShell and should be inside **C:\workshop**.
- The **.env** file already exists in **C:\workshop**; attendees add values to it rather than creating a new one.
- The attendee copies the game-specific **GAME_MCP_URL** from the rendered instructions into **.env**.

## Workshop Writing Style

- Instructions are shared Markdown lessons rendered per game, not delivered through Skillable.
- Use bold text for plain folder names and paths in prose, for example **C:\workshop** and **C:\workshop\.env**.
- Avoid inline code for plain folder/path references in prose unless it is actual code, a command fragment, an environment variable name, a literal value, or an error message.
- Keep workshop step files simple: headings, paragraphs, ordered lists, unordered lists, and fenced code blocks.

## Per-Game Player Content

- Guided sources live in `player/guided/`; Challenge sources live in `player/challenge/`; the dashboard serves `/<slug>/player`.
- Game variables are documented in `player/README.md`. Use the allowlisted placeholders, never credentials or executable templates.
- Each game can have start/end datetimes, an IANA timezone, and a Player mode, edited in **Schedule & player**. The MCP server enforces the play window; Player content remains public before and after it.
- Admin and dashboard container builds include the shared lessons and screenshots. Redeploy them after source edits; local development reads the source directly.
- `player/skillable.md` and `player/index.html` are legacy Guided Mode exports from `scripts/sync-to-skillable.py`, not the current delivery path. Do not regenerate them for per-game content changes.
