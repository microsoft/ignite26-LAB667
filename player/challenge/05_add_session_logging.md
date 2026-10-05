# Make Every Run Observable

Your goal is to capture enough structured information to understand why the agent made each decision. This matters when debugging tool selection, unexpected model behavior, or incorrect mission answers.

## Challenge

Add per-session logging around model activity and tool execution without leaking credentials. Logs should make the sequence of prompts, responses, tool calls, tool results, and errors inspectable after the run.

## Expected outcome

- Each run creates a distinct session log.
- Model input and output are identifiable.
- Tool names, arguments, results, timing, and failures are recorded.
- Sensitive environment values are excluded or redacted.
- Logging failures do not masquerade as successful game actions.

## Completion check

After a game interaction, the session log tells a coherent story from user request through model reasoning boundary, tool calls, and final response.
