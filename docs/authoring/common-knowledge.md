# Common repository knowledge

These conventions describe the existing workshop content and prepared lab
environment. See the [contributor guide](../../CONTRIBUTING.md) for project
development and maintenance.

Use these facts when editing documentation, workshop steps, README content, or generated workshop materials.

## Product names

- Use **Microsoft Foundry**.
- Do not write **Azure AI Foundry** or **Azure Foundry**.
- **Azure OpenAI** is still valid when referring to the model endpoint, deployment, or API key.
- **Azure AI Search** is valid when referring to the search service or knowledge base backing retrieval.
- **Microsoft Agent Framework**, **MCP**, and **A2A** are valid workshop terms.
- **Agent42** is the transport expert agent.
- **Lost in the City** is the workshop/game family name.

## Lab environment

- The attendee works inside the Windows 11 lab VM.
- The workshop folder on the lab VM is **C:\workshop**.
- Tell attendees to open VS Code by clicking the **Visual Studio Code** icon on the Windows desktop.
- The **C:\workshop** folder should already be open in VS Code.
- The terminal should be PowerShell and should be inside **C:\workshop**.
- The **.env** file already exists in **C:\workshop**; attendees add values to it rather than creating a new one.
- The attendee copies the game-specific **GAME_MCP_URL** from the rendered instructions into **.env**.

## Workshop writing style

- Current lessons are rendered on the game's Player page, not delivered through Skillable.
- Use bold text for plain folder names and paths in prose, for example **C:\workshop** and **C:\workshop\.env**.
- Avoid inline code for plain folder/path references in prose unless it is actual code, a command fragment, an environment variable name, a literal value, or an error message.
- Keep workshop step files simple: headings, paragraphs, ordered lists, unordered lists, and fenced code blocks.

## Player sources and legacy exports

- Current Guided and Challenge chapters live in
  [player/](../../player/README.md). Redeploy the admin and dashboard after
  changing lessons or screenshots; local development reads the source directly.
- [player/index.html](../../player/index.html) is an archived index for the
  legacy delivery path. The Skillable import file and its generator have been
  removed. Update the shared lesson sources for current sessions.
