# Arrived: Complete the Game

Complete the remaining missions and reach the destination for {{ game_event }}.
Ask Agent42 for travel advice when needed. If the game presents a secret note
at arrival, add a vision-based Note Reader to recover its password.

## Objectives

1. Resume the authenticated player and inspect the remaining mission.
2. For a movement mission, send the complete origin and destination to Agent42.
3. Review the recommendation and submit its supported transport answer and
   route reference to MCP.
4. If the next mission supplies a secret-note image, use a vision model to
   read it and return its language, translation, and password as structured
   output. Submit the recovered password to MCP; do not guess it or use the
   city guide for this mission.
5. Continue until MCP reports that the quest is complete.
6. Confirm the completed state in the **Your Quest** sidebar on the right.
   If Competitive Mode is enabled, also check the leaderboard.

## Rules

- Reuse the existing authenticated MCP and Agent42 clients.
- Let MCP decide whether an answer completes a mission or the game.
- Do not bypass remaining missions or manually inject progress.
- Investigate failures without exposing credentials.

## Completion check

The **Your Quest** sidebar on the right shows the completed missions, including
the secret-note question when present, and MCP reports a completed quest.
In Competitive Mode, the nickname also appears on the {{ game_name }} leaderboard.
