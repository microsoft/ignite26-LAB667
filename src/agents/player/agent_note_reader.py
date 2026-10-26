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
