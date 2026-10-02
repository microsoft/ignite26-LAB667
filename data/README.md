# Data

The [city-guide/](city-guide/) folder contains 20 San Francisco guide chapters
used as the retrieval source for the city-guide specialist.

The [city-guide exercise](../instructions/07_test_the_city_guide_agent.md)
explains how to connect the uploaded guide content to Azure AI Search.
The local folder name does not change the `city-guide` blob container name.

Game seed quests remain with the server in
[quests.json](../src/services/game-server/quests.json), so its container can
load them without an additional data mount.
