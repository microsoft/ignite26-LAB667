# Chapter 3: Solve the Quest with Foundry IQ

At the checkpoint, the game gives you a question. Use **Foundry IQ** and the
provided {{ game_city }} data to answer it. The city guide chapters are already
in your lab's Blob Storage, in the **city-guide** container; no download or
upload is needed. Add Foundry IQ to the player so the answer is grounded in
those documents rather than guessed from model memory.

## Objectives

1. Inspect the question returned by the game MCP server.
2. Locate the provided **city-guide** container in your lab's storage account.
3. Create a Foundry IQ knowledge base using that Azure Blob Storage source.
4. Add the Foundry IQ knowledge base as a focused tool for the player agent.
5. Retrieve evidence that directly supports the current question.
6. Make the agent refuse to fabricate an answer when the document does not
   contain enough evidence.
7. Submit only the grounded answer to MCP and continue only after the game
   accepts it.

## Rules

- The supplied documents are the authority for the question.
- Keep Foundry credentials and connection details in **C:\workshop\\.env**.
- Do not embed the expected answer in source code or agent instructions.
- Keep retrieved evidence separate from the private Player API key.
- Surface retrieval and grounding failures instead of returning a
  success-shaped guess.

## Completion check

The player uses Foundry IQ to retrieve supporting evidence, submits a grounded
answer, and MCP confirms that the question is solved and reveals the final
travel mission.
