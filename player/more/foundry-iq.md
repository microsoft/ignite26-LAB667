# Foundry IQ: knowledge retrieval

Language models only know what they were trained on. To answer questions
about specific content, such as the {{ game_city }} city guide, your agent must
find the right facts when it needs them and base its answer on them. This
pattern is called retrieval-augmented generation (RAG).

**Foundry IQ** is the knowledge layer of Microsoft Foundry, powered by Azure AI
Search. You set up a knowledge base once, and any agent can use it.

## How it works

- **Knowledge source**: the content to search, such as documents in Azure Blob
  Storage. Azure AI Search splits the text into chunks and indexes it for
  keyword and vector search.
- **Knowledge base**: combines one or more knowledge sources and the settings
  for retrieving from them.
- **Agentic retrieval**: when your agent asks a question, the knowledge base
  uses a model to plan the search. It breaks the question into focused
  subqueries, runs them, ranks the results, and returns the most relevant
  passages with references to their sources.

Your agent then answers from those passages instead of guessing.

Every knowledge base is also an MCP server. It offers one tool,
**knowledge_base_retrieve**, so any agent that speaks MCP can use it, just like
the game server.

## In this workshop

Question missions need answers from the {{ game_city }} city guide. In the
Microsoft Foundry portal, you create a knowledge base over the guide. Then you
build a city guide specialist agent that connects to the knowledge base over
MCP. Your game agent asks this specialist only when a guide question appears,
so it doesn't spend search tokens on every turn.
