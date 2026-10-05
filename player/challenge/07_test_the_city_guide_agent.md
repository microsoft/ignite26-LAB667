# Add City Guide Retrieval

Your goal is to answer city questions from the trusted {{ game_city }} guide rather than from model memory. This matters because question missions expect facts grounded in the workshop knowledge source.

## Challenge

Create a retrieval-backed city guide specialist using Azure AI Search and verify it independently. The specialist should cite or clearly ground its answer in retrieved guide content and should acknowledge when the source does not support an answer.

## Expected outcome

- The city guide connects to the intended Azure AI Search knowledge base.
- Questions retrieve relevant {{ game_city }} content.
- Answers are grounded in retrieved material.
- Missing evidence does not produce a confident fabricated answer.
- The specialist can be exposed to the main player as a focused tool.

## Completion check

A representative city question returns the expected fact from the guide, with enough retrieval evidence to understand where the answer came from.
