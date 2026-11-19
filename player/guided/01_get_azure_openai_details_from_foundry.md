# Get your model endpoint

In this exercise, you collect the connection details from Microsoft Foundry so
the agent can call the deployed chat model. Every later step uses the same
endpoint, API key, and deployment name from the existing **.env** file.
[What is a .env file?](#more-env-file)


## Log in to Microsoft Foundry

1. Open the Edge browser.
2. Navigate to **https://ai.azure.com** in the browser's address bar, if it's not already open.
3. Click **Sign in** in the top-right corner.
![The Microsoft Foundry home page at ai.azure.com with the Sign in buttons highlighted in the top-right corner and below the headline](../assets/illustration-foundry-sign-in.webp)
4. Sign in with the Microsoft Foundry credentials from the **Resources** tab in Skillable.
5. After you sign in, you see a list of projects. Click the project name.
![The Microsoft Foundry All resources list with one project, with the project name link highlighted and labeled click your project](../assets/illustration-foundry-select-project.webp)
6. When the **Your project is set up. What would you like to do next?** box appears, click **X** in the top-right corner.
![The Microsoft Foundry project home page with the Your project is set up box open and its X button highlighted, labeled close this box](../assets/illustration-foundry-close-setup-box.webp)

## Get your endpoint details

After you close the box, you should see the Microsoft Foundry home page
with **API key**, **Project endpoint**, and **Azure OpenAI endpoint** boxes near
the top of the page.
![Foundry to VS Code: copy the API key from Microsoft Foundry after AZURE_OPENAI_API_KEY= and the Azure OpenAI endpoint after AZURE_OPENAI_ENDPOINT= in the .env file](../assets/illustration-foundry-to-env.webp)

1. Open the existing **.env** file in **C:\workshop** in VS Code.
2. Copy the value from the **Azure OpenAI endpoint** box and paste it after
    **AZURE_OPENAI_ENDPOINT=**. Paste it as shown in Microsoft Foundry. The
    agent code removes `/openai/v1` if it appears at the end of the URL.
3. Copy the value from the **API key** box and paste it after
    **AZURE_OPENAI_API_KEY=**.
4. Save **.env**.
![The .env file open in an editor with AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY filled in, while a pigeon holds a checklist saying your .env is ready](../assets/illustration-env-ready.webp)

## Get your model deployments

The workshop already deployed the models your agent needs in Microsoft Foundry.
Check that they are ready and that your **.env** file uses the right deployment
name for the main model.
![The Microsoft Foundry Build menu and Models page with step 1 on Build and step 2 on Models, three deployments all showing Succeeded, and the gpt-5.6-luna name matched to AZURE_OPENAI_DEPLOYMENT_NAME in the .env file](../assets/illustration-foundry-models.webp)

1. In the top navigation, select **Build**.
2. Open **Models**.
3. Confirm that these three models are listed and each one has a **Succeeded**
    deployment status:
    - **gpt-5.6-luna**: the main game agent and knowledge base retrieval.
    - **gpt-4.1-mini**: content extraction for the city guide knowledge source.
    - **text-embedding-3-small**: turns the city guide into vectors for search.
4. Confirm that **AZURE_OPENAI_DEPLOYMENT_NAME** in **.env** matches **gpt-5.6-luna**.
![The .env file open in an editor with AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5.6-luna, while a pigeon holds a checklist saying your .env is ready](../assets/illustration-env-complete.webp)

## What You Learned

You signed in to Microsoft Foundry, copied your endpoint and API key into the
**.env** file so your agent can use them, and found your model deployments.

![Ready for the next mission: a checklist showing signed in to Foundry, endpoint and API key saved in .env, and model deployments checked, with a player taking notes beside a pigeon](../assets/illustration-foundry-recap.webp)
