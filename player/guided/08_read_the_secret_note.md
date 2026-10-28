# Note Reader Specialist

![Test the Note Reader separately: send an image of the secret note to the specialist, which detects the language, translates the text, and returns a SecretNote with language, translation, and password fields](../assets/illustration-note-reader-header.png)

At the door of Microsoft Ignite, the host asks for a secret password. You
remember the folded piece of paper you got at the start of your quest, but it's
written in a strange language. Instead of guessing, your agent can ask a **Note
Reader**: a small specialist agent that looks at a picture of the note, detects
the language, translates it, and finds the password.

The Note Reader answers with structured output. Instead of free text, it
returns a **SecretNote** object with three fields: the language, a translation,
and the password. Your code reads those fields directly. In this exercise, you
build the Note Reader in a separate file and test it on its own, before you add
it to your game agent.

[Read more about structured output](#more-structured-output)

## Create the Note Reader tool

You create a new file, **agent_note_reader.py**, that turns the Note Reader into
a tool your game agent can use. It does five things:

- **SecretNote** describes the structured answer: **language**, **translation**,
  and **password**.
- **build_note_reader_agent()** creates the Note Reader agent. It uses the same
  **gpt-5.6-luna** model as your game agent, which can read images.
- **read_note()** sends a link to a picture of a note to the Note Reader and asks
  for a **SecretNote** back.
- **build_note_reader_tool()** wraps **read_note()** as a tool called
  **read_secret_note**. Later, your game agent calls this tool at the door, with
  the link to the note that the game gives it.
- **main()** reads a sample note once, so you can check that the Note Reader
  works before you add it to your game agent. The real note stays a secret until
  you reach the door.

## Create agent_note_reader.py

![In VS Code, select the workshop folder, create agent_note_reader.py, and paste the complete code from the instructions, including the SecretNote model with language, translation, and password fields](../assets/illustration-note-reader-create-file.png)

1. In the VS Code Explorer, select the **C:\workshop** folder.
2. Select **New File** and name it **agent_note_reader.py**.
3. Copy the code below with the **Copy** button and paste it into
   **agent_note_reader.py**. VS Code saves the file automatically.

```python-notype
"""Note reader specialist that reads a note image with structured output."""

import asyncio
import mimetypes
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from agent_framework import Agent, Content, FunctionTool, Message, tool
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv
from pydantic import BaseModel, Field

SAMPLE_NOTE_URL = "https://lab667.blob.core.windows.net/images/secret-note-sample.png"


class SecretNote(BaseModel):
	language: str = Field(description="The language the note is written in.")
	translation: str = Field(description="The full note translated to English.")
	password: str = Field(description="The secret password, exactly as written on the note.")


@asynccontextmanager
async def build_note_reader_agent() -> AsyncGenerator[Agent, None]:
	client = OpenAIChatClient(
		azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
		api_key=os.environ["AZURE_OPENAI_API_KEY"],
		model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
	)
	async with client.client:
		yield Agent(
			client=client,
			name="Note Reader",
			instructions=(
				"You read photos of handwritten notes. Detect the language the note is "
				"written in, translate the whole note to English, and find the secret "
				"password. Return the password exactly as it is written on the note."
			),
		)


async def read_note(note_reader: Agent, image_url: str) -> SecretNote:
	# Send the image link to the model and ask for a SecretNote back.
	media_type = mimetypes.guess_type(urlsplit(image_url).path)[0] or "image/png"
	message = Message("user", [
		Content.from_text("Read this note."),
		Content.from_uri(image_url, media_type=media_type),
	])
	response = await note_reader.run(message, options={"response_format": SecretNote})
	return response.value


def build_note_reader_tool(note_reader: Agent) -> FunctionTool:
	# The main game agent calls this tool when it needs the secret password.
	@tool(
		name="read_secret_note",
		description=(
			"Read a note from the image URL the game gives you. "
			"Returns the language, an English translation, and the secret password."
		),
	)
	async def read_secret_note(
		image_url: Annotated[str, Field(description="The URL of the note image from the game.")],
	) -> SecretNote:
		return await read_note(note_reader, image_url)

	return read_secret_note


async def main() -> None:
	load_dotenv(Path(__file__).with_name(".env"), override=True)

	async with build_note_reader_agent() as note_reader:
		note = await read_note(note_reader, SAMPLE_NOTE_URL)
		print(f"Language: {note.language}")
		print(f"Translation: {note.translation}")
		print(f"Password: {note.password}")


if __name__ == "__main__":
	asyncio.run(main())
```

Not sure what the code above does? Click the button below for a step-by-step
explanation of each part.

[Explain the code](#more-note-reader-code)

## Test the Note Reader

![Run python agent_note_reader.py in the VS Code terminal and inspect the sample note's language, translation, and password fields; the note at the door comes next](../assets/illustration-note-reader-test.png)

Run **agent_note_reader.py** from the VS Code terminal:

```powershell
python agent_note_reader.py
```

The sample note is a short poem in English that ends with a riddle. The Note
Reader looks at it and fills in the three fields of **SecretNote**. The wording
can differ, but it looks like this:

```output-read
Language: English
Translation: Beyond the edge, new paths appear, ... What is the name that carries us through?
Password: <the Note Reader's answer to the riddle>
```

The note at the door looks different. In the next lesson, your game agent reads
that note on its own.

## What You Learned

You built a Note Reader specialist that uses a vision-capable model to read a
note image from a URL.

- **Image input:** you sent the note image and a text instruction to the model.
- **Structured output:** you defined **SecretNote** with Pydantic and requested
  it as the response format. Your code reads **language**, **translation**, and
  **password** directly instead of extracting them from a free-text reply.
- **Function tool:** you prepared **read_secret_note**, a custom tool that lets
  the game agent ask the Note Reader to read an image.
- **Standalone testing:** you ran the reader on a sample note and inspected
  the three returned fields before connecting it to the game.

Structured output gives your code a predictable response shape; it does not
guarantee that the model read or interpreted the note correctly.

The Note Reader is not connected to your game agent yet. In the next lesson,
you add **read_secret_note** to its tools and use the note image supplied by
the game to tackle the password challenge at the door.

![Ready for the next mission: image and instruction sent, SecretNote structured output defined with Pydantic, read_secret_note tool prepared, and sample note tested separately; check the reading, then add the tool to the game agent](../assets/illustration-note-reader-recap.png)
