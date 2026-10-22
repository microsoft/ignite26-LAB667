# The .env file

A **.env** file is a plain text file that holds configuration values for your
app, one per line, as **NAME=value**. It keeps settings such as endpoints, API
keys, and model names out of your code.

## How it works

![A .env file with ENDPOINT, API_KEY, and MODEL settings, one per line and kept private, loaded by load_dotenv() into a Python app that reads os.environ["API_KEY"]; .env is listed in .gitignore to keep it out of Git, and a .env.example template is shared instead](../assets/illustration-more-env-file.webp)

- Each line sets one environment variable, for example
  **AZURE_OPENAI_ENDPOINT=https://foundry-12345.openai.azure.com**.
- Don't add quotes or spaces around the **=** sign.
- Lines that start with **#** are comments.
- When the agent starts, it calls **load_dotenv()** from the **python-dotenv**
  package. That reads **.env** and makes each value available to the code
  through **os.environ**, for example **os.environ["AZURE_OPENAI_API_KEY"]**.

## In this workshop

The **.env** file is already in **C:\workshop**. You add values to it as you go:
the Microsoft Foundry endpoint and API key, the game server URL, your Player API
key, and the Azure AI Search settings for the city guide. Every script in the
workshop reads the same file, so you set each value once.

## Keep it private

A **.env** file often contains secrets, such as API keys. Don't share it, paste
it into chats, or commit it to source control. Projects usually list **.env** in
**.gitignore** and share a **.env.example** file with empty values instead.
