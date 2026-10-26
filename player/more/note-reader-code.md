# The Note Reader code

**agent_note_reader.py** defines the shape of the answer, creates the Note
Reader, sends it the picture of the note, and turns it into a tool for your game
agent. The numbers below follow the code from top to bottom.

## Step by step

1. **Imports**: **Content** and **Message** build a message that holds both text
   and an image. **tool** turns a Python function into a tool the model can call.
   **BaseModel** and **Field** come from Pydantic and describe the structured
   answer.
2. **SAMPLE_NOTE_URL**: a link to a sample note for the test. The real note
   comes from the game at the door.
3. **SecretNote**: the shape of the answer. Each field has a description, so the
   model knows what to put in it.
4. **build_note_reader_agent()**: creates the Note Reader with the same model as
   your game agent. Its instructions tell it to detect the language, translate
   the note, and find the password.
5. **read_note()**: the image call.
   - **Content.from_uri(...)**: attaches the image link to the message with its
     media type, for example **image/png**. The model downloads the image itself.
   - **response_format=SecretNote**: asks the model to answer as a
     **SecretNote** instead of free text.
   - **response.value**: the answer, already turned into a **SecretNote**
     object.
6. **build_note_reader_tool()**: the **@tool** decorator turns
   **read_secret_note()** into a tool. Its description tells the game agent when
   to use it, and **image_url** is the one argument the game agent fills in with
   the link from the game. The tool returns the **SecretNote**, which reaches the
   model as JSON.
7. **main()**: the test. It loads **.env**, reads the sample note once, and
   prints the three fields.

## Why a separate agent

Your game agent could look at the image itself, but then every turn of the
game would carry the picture. The Note Reader only runs when the game agent
calls **read_secret_note**, and it returns three short fields instead of a long
answer.

## Try your own image

Find a public image of a short note or sign in another language, and change
**SAMPLE_NOTE_URL** to its link. Run **agent_note_reader.py** again and see
which language the Note Reader detects.
