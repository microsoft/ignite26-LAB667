# City Guide Part 1: Create the Knowledge Base

Some missions ask a question about the city: where a park is, what a
neighborhood is known for, or where locals go for coffee. Instead of guessing,
your agent can ask a **City Guide** specialist that looks up the answer in the
{{ game_city }} city guide.

The city guide lives in a **Foundry IQ** knowledge base. In this part, you
create that knowledge base in the Microsoft Foundry portal and test it there.
In part 2, you connect it to a small agent of your own.

[Read more about Foundry IQ](#more-foundry-iq)

## Connect to the knowledge resource

Foundry IQ stores its knowledge bases in Azure AI Search. Your lab already has
a Search service; you connect it to your Foundry project once.

![The Foundry portal Knowledge (Foundry IQ) page: 1 select Build, 2 select Knowledge, 3 select the existing search resource, 4 keep Auth Type API Key, 5 select Connect](../assets/illustration-foundry-iq-connect.webp)

1. In the Microsoft Foundry portal, select **Build** in the top menu, then
   **Knowledge** in the left menu.
2. For **Foundry IQ resource**, select the resource that starts with
   **search-**. There is only one.
3. For **Auth Type**, keep **API Key**.
4. Select **Connect**.

## Create the knowledge base

The city guide chapters are already uploaded to your lab's storage account, in
a container named **city-guide**. You turn them into a knowledge base. On the
**Knowledge (Foundry IQ)** page, click the **Create a knowledge base** button.

### Basic configuration

![The Create a new knowledge base form: 1 Name san-francisco-cityguide, 2 the description, 3 Chat completions model gpt-5.6-luna, 4 Retrieval reasoning effort Low, 5 the retrieval instructions, 6 Output mode Answer synthesis](../assets/illustration-foundry-iq-configure.webp)

Fill in these settings:

| # | Setting | Value |
| --- | --- | --- |
| 1 | **Name** | san-francisco-cityguide |
| 2 | **Description** | San Francisco city guide with neighborhoods, history, food, culture, transit, and local knowledge. |
| 3 | **Chat completions model** | gpt-5.6-luna |
| 4 | **Retrieval reasoning effort** | Low |
| 5 | **Retrieval instructions** | Search the San Francisco city guide. Prefer chapters about neighborhoods, landmarks, and local knowledge. |
| 6 | **Output mode** | Answer synthesis |

### Knowledge sources

A knowledge source is the content your knowledge base searches. Foundry IQ can
combine several, such as files in Blob Storage, SharePoint sites, or the web.
For the City Guide you need just one: the city guide chapters in your lab's
Blob Storage. When you add it, Foundry IQ splits the chapters into small
passages and indexes them, so it can find the right passage for each question.

![Add the city guide source: 1 under Knowledge sources click Add sources, 2 select Azure Blob Storage](../assets/illustration-foundry-iq-add-source.webp)

1. Under **Knowledge sources**, click **Add sources**.
2. Select **Azure Blob Storage**.
3. In the **Create a knowledge source** window, keep the suggested **Name** and
   fill in these settings on the **General** tab:

![Configure the Blob source: 1 Storage account, 2 Container name city-guide, 3 Authentication type API Key, 4 Content extraction mode Minimal, 5 Embedding model text-embedding-3-small, 6 Chat completions model gpt-4.1-mini, 7 Create](../assets/illustration-foundry-iq-blob-source.webp)

| # | Setting | Value |
| --- | --- | --- |
| 1 | **Storage account** | The account that starts with **stor**. There is only one. |
| 2 | **Container name** | city-guide |
| 3 | **Authentication type** | API Key |
| 4 | **Content extraction mode** | Minimal |
| 5 | **Embedding model** | text-embedding-3-small |
| 6 | **Chat completions model** | gpt-4.1-mini |

4. Click **Create** at the bottom of the window. The window closes, and your
   new Azure Blob Storage source appears under **Knowledge sources**.
5. Click **Save knowledge base** at the top right of the page. This creates
   the **san-francisco-cityguide** knowledge base with the settings and the
   source you just added.

Foundry IQ now reads the city guide and indexes it. This takes a minute or two.

![A little reading time: while a player waits with a coffee, the laptop shows Indexing city guide, usually 1 to 2 minutes, and the chapters turn into searchable passages](../assets/illustration-foundry-iq-indexing.webp)

## Test the knowledge base

Try the knowledge base with a quick test agent in the portal.

1. On the **san-francisco-cityguide** knowledge base page, click
   **Use in an agent**.
2. Give the agent a name, for example **city-guide-test**, and create it.
3. In the agent's chat, ask:

```text
What neighborhood is Dolores Park in?
```

The answer mentions **the Mission**. If it says it can't find the answer, wait a
minute while indexing finishes and ask again.

## What You Learned

You connected Foundry IQ to your lab's Azure AI Search service and created the
**san-francisco-cityguide** knowledge base over the city guide chapters. You
tested it in the portal, and it answered from the city guide.

Next, you connect this knowledge base to the City Guide agent.
