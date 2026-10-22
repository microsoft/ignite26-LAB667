# Middleware

Middleware is code that wraps around a step your agent takes. It runs just
before the step and just after it, so it can look at what goes in and what comes
out. You don't call middleware yourself. You give it to the agent once, and the
agent runs it automatically every time.

A good comparison is a security checkpoint. Every traveler passes through it on
the way in and out. The checkpoint can note who passed, check what they carry,
or stop them, but the traveler's journey stays the same.

## How it works

Each middleware function receives two things:

- **context**: information about the current step, such as the messages, the
  tool that is being called, and later the result.
- **call_next**: a function that runs the step itself.

The pattern is always the same:

```python-read
async def log_function(context, call_next):
    # Before: runs before the tool call.
    await call_next()
    # After: runs after the tool call. context.result now holds the answer.
```

Code before **await call_next()** runs first. Then the step runs. Code after it
runs once the step is done. If middleware never calls **call_next()**, the step
doesn't run at all, which is how middleware can block something.

## Three places to plug in

Microsoft Agent Framework lets you wrap three kinds of steps. The session log
uses all three:

- **Agent middleware** (**@agent_middleware**) wraps a whole agent run, from
  your message to the final reply. The log uses it to write **USER ->** and
  **AGENT <-**.
- **Chat middleware** (**@chat_middleware**) wraps each request to the model.
  One agent run can make several requests, for example before and after a tool
  call. The log uses it to write **MODEL INPUT ->**.
- **Function middleware** (**@function_middleware**) wraps each tool call. The log
  uses it to write **TOOL CALL** with the arguments and **TOOL RESULT** with the
  answer.

## What else middleware is used for

Logging is the simplest use. Middleware is also used to:

- **Check safety**: block a message or tool call that breaks a rule.
- **Change data**: add details to a request or clean up a result.
- **Measure**: track how long each model request or tool call takes.
- **Ask for approval**: pause before a sensitive tool runs.

## Watch and control your agent

An agent makes its own decisions: which tool to call, with which arguments, and
how often. Middleware gives you one place to watch and control all of those
decisions, without changing the agent, its tools, or the model.
