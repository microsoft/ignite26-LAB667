<a name="start-building"></a>

<p align="center">
<img src="img/banner-ignite-26.png" alt="Microsoft Ignite 2026" width="100%"/>
</p>

# [Microsoft Ignite 2026](https://ignite.microsoft.com)

## 🔥LAB667: Building multi-agent systems. Lost in San Francisco

> This session repository is still being prepared. Session details and setup
> steps below remain to be completed before publication.

### Session description

Add your session description here. Keep it concise — 2-3 sentences about what attendees will learn and why it matters.

### 🚀 Getting started

#### In a guided session

If you're following along during a live session:

1. Step 1
2. Step 2
3. Open [`instructions/`](instructions/README.md) when this session includes
   attendee step-by-step guidance

#### On your own

If you're learning at your own pace:

1. Clone this repository
2. Set up your environment
3. Follow the session guidance in [`instructions/`](instructions/README.md), or
   use the linked docs-site entry point when this repository uses that pattern

### Repository layout

| Folder | Contents |
| --- | --- |
| [src/](src/README.md) | Shared game services, Agent42, and the reference player agent |
| [instructions/](instructions/README.md) | Numbered attendee walkthrough and screenshots |
| [data/](data/README.md) | San Francisco city-guide source material for retrieval |
| [docs/](docs/README.md) | Workshop overview, local setup, gameplay, and authoring references |
| [infra/](infra/README.md) | azd shared-service deployment and inactive legacy workflows |
| [skillable/](skillable/README.md) | Skillable-specific documentation and infrastructure |
| [scripts/](scripts/README.md) | Workshop export and local load-testing utilities |

For the existing workshop setup and service run commands, see the
[workshop overview](docs/workshop-overview.md).

For development, lesson maintenance, and deployment guidance, see
[Contributing](CONTRIBUTING.md).

### Develop in Codespaces

Open this repository with **Code > Codespaces > Create codespace**. The
[development container](.devcontainer/devcontainer.json) includes Python 3.12,
Azure CLI (`az`), Azure Developer CLI (`azd`), Bicep, Git LFS, and Docker with Compose.

For an existing Codespace, run **Codespaces: Rebuild Container** from the
VS Code command palette to apply the configuration. This restarts the
development environment; save your work first. Local VS Code users can use
**Dev Containers: Reopen in Container** with Docker running.

The container checks tool versions after creation, but does not sign in,
deploy resources, install application dependencies, or start the services.
See [local development](CONTRIBUTING.md#local-development) for service setup.
Keep forwarded ports **Private**, including the admin port.

### Deploy the shared services

With Azure Developer CLI and Docker installed, run from the repository root:

```bash
azd auth login
azd env new lab667-dev
azd up
```

In Codespaces, if browser sign-in cannot complete, use
`azd auth login --use-device-code`. Azure CLI has its own login:
`az login --use-device-code` when you need `az` commands against your subscription.

This deploys the MCP server, dashboard, admin UI, and Agent42, including storage,
Maps, and a dedicated `gpt-5.6-luna` model. Attendee model/search resources remain
separate. **Sign in to the admin UI with `admin` / `admin` and change the
password before managing games.** Restrict access until this setup is complete.
Review [deployment prerequisites, costs, and access limitations](infra/README.md)
before running it.

### 🎯 Learning outcomes

By the end of this session, you will be able to:

- Outcome 1
- Outcome 2
- Outcome 3

### 💻 Technologies used

- Technology 1
- Technology 2
- Technology 3

### 📚 Continue your learning

Pick your next step based on your learning style:

| Resource | What you'll get |
|----------|-----------------|
| **[Ignite 2026 Next Steps](https://aka.ms/ignite26-next-steps)** | Additional session repos and materials from Microsoft Ignite 2026 |
| **[Microsoft AI Skills Navigator](https://aka.ms/ignite26-asn)** | Discover AI skills, learning paths, and resources for your next step |
| **[Microsoft Learn](https://aka.ms/ignite26-learn)** | Official documentation and guided learning paths on these topics |
| **[Microsoft Foundry Community](https://aka.ms/MicrosoftFoundryDiscord-Ignite26)** | Connect with other learners and experts in our Discord community |

### 🌟 Microsoft Learn MCP Server

<!-- Remove this section if the Microsoft Learn MCP Server is not relevant to the session. -->

The Microsoft Learn MCP Server gives your AI agent direct access to Microsoft's official documentation — grounded, up-to-date answers about the topics in this session.

**GitHub Copilot CLI** — Install with:

```shell
copilot plugin install microsoftdocs/mcp
```

**VS Code** — One-click install:  
[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_Microsoft_Learn_MCP-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=microsoft-learn&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Flearn.microsoft.com%2Fapi%2Fmcp%22%7D)

For more information, visit the [Learn MCP Server repo](https://aka.ms/learnmcp).

### 👥 Content owners

<!-- TODO: Add yourself as a content owner
1. Change the src in the image tag to {your github url}.png
2. Change INSERT NAME HERE to your name
3. Change the github url in the final href to your url. -->

<table>
<tr>
    <td align="center"><a href="http://github.com/yourGitHubHandle">
        <img src="https://github.com/yourGitHubHandle.png" width="100px;" alt="INSERT NAME HERE"/><br />
        <sub><b>INSERT NAME HERE</b></sub></a><br />
            <a href="https://github.com/yourGitHubHandle" title="talk">📢</a>
    </td>
</tr></table>

### ⚖️ Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.

Any use of third-party trademarks or logos are subject to those third-party's policies.
