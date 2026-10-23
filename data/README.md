# Data

The [city-guide/](city-guide/) folder contains 20 San Francisco guide chapters
used as the retrieval source for the city-guide specialist.

The [city-guide exercise](../player/guided/07_create_the_city_guide_knowledge_base.md)
explains how to turn the uploaded guide content into a Foundry IQ knowledge base.
The local folder name does not change the `city-guide` blob container name.

Game seed quests remain with the server in
[quests.json](../src/services/game-server/quests.json), so its container can
load them without an additional data mount.
