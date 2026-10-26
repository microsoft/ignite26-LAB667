# Structured output

By default, a model answers with free text. That works for people, but code
that needs one specific value, such as a password, would have to dig through
the sentences to find it. With structured output, you tell the model exactly
which fields to return, and it answers with data in that shape.

## How it works

- **Describe the shape**: you write a small Pydantic class, such as
  **SecretNote**, with a field for each value you need and a description for
  each field.
- **Ask for that shape**: you pass the class as **response_format** when you run
  the agent. The model then answers with JSON that matches the class.
- **Use the fields**: **response.value** turns the JSON back into an object, so
  your code reads **note.password** instead of parsing text.

## In this workshop

The Note Reader returns a **SecretNote** with three fields: **language**,
**translation**, and **password**. Your game agent gets the same fields when it
calls the **read_secret_note** tool, so it can tell you what the note says and
give the host the exact password.
