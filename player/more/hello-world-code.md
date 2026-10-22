# The hello-world code

The program connects to your model, creates an agent, sends it one message, and
prints the reply. The numbers below follow the code from top to bottom.

## Step by step

1. **Imports**: **asyncio** runs asynchronous code, **os** reads environment
   variables, and **Path** builds a file path. **Agent** and
   **OpenAIChatClient** come from the Microsoft Agent Framework. **load_dotenv**
   comes from the **python-dotenv** package.
2. **async def main()**: the agent talks to the model over the network, so the
   work happens in an asynchronous function. It lets Python wait for the reply
   without freezing.
3. **load_dotenv(...)**: reads the **.env** file that sits next to
   **agent.py**, so it works even if you start the program from another folder.
   With **override=True**, the values in **.env** win over any environment
   variable that is already set.
4. **OpenAIChatClient(...)**: the connection to your model in Microsoft
   Foundry. It gets the endpoint, the API key, and the deployment name from
   **.env** through **os.environ**.
5. **async with client.client**: keeps the connection open while the block
   runs and closes it automatically at the end, even if an error occurs. Keep
   the agent code indented inside this block.
6. **Agent(...)**: wraps the client into an agent. The **name** labels it, and
   the **instructions** are its system prompt, which sets how it behaves. Here
   it is a friendly workshop agent that replies briefly.
7. **await agent.run(...)**: sends your message to the model and waits for the
   answer. **response.text** holds the reply, and **print** shows it in the
   terminal.
8. **asyncio.run(main())**: starts the program. The
   `if __name__ == "__main__"` check makes it run only when you start
   **agent.py** directly.

## What you can change

- Change the text in **agent.run(...)** to ask something else.
- Change the **instructions** to give the agent a different personality.

The next missions build on this agent. You add the game server as tools, then
Agent42 and the city guide as helpers.
