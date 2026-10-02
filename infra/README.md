# Infrastructure

## Deploy shared services with azd

[azure.yaml](../azure.yaml) and [main.bicep](main.bicep) deploy one shared
workshop environment containing:

- Four Azure Container Apps: game MCP server, dashboard, admin UI, and Agent42.
- A Container Apps environment, Basic container registry, and Log Analytics.
- One storage account for game tables and the `agent42-routes` blob container.
- An Azure Maps account.
- A dedicated Azure OpenAI account and an `agent42` model deployment using
  `gpt-5.6-luna`, version `2026-07-09`, with the `GlobalStandard` SKU.

The attendee player agent, attendee model deployments, Azure AI Search, guide
indexing, and instruction hosting are **not** included. The game seeds
San Francisco automatically; the model configuration applies only to Agent42.

> **Temporary workshop deployment:** all four service endpoints are public,
> but the admin UI and its APIs require a login. The initial credentials are
> `admin` / `admin`; change the password immediately before opening access to
> others. The first person using these known defaults can claim the account.
> Other service endpoints remain unauthenticated. Agent42 requests can incur
> model and Maps charges. Route PNG/JSON blobs are readable by URL (not publicly
> listable), and the dashboard's Maps key is sent to the browser. Do not use
> sensitive data; add access controls before broader use.

### Prerequisites

- The repository's [Codespaces configuration](../.devcontainer/devcontainer.json)
  supplies Azure CLI, azd, Bicep, and Docker/Compose. Create a new Codespace or
  run **Codespaces: Rebuild Container** in an existing one, then check
  `az version`, `azd version`, and `docker info`.
- [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
  and a running Docker engine for local Linux/amd64 image builds if you are not
  using the development container.
- An Azure subscription where you can create resource groups and the listed
  resources, read their keys, and push container images.
- Regional availability and quota for the selected model and deployment SKU.
  Check [Foundry model availability](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure)
  for your subscription. A model appearing in a catalog does not guarantee
  deployment capacity in a particular region.
- Subscription policies must permit key-based access and anonymous route-blob
  reads. The current applications use these; this template does not bypass
  policies that prohibit them.

### First deployment

From the repository root:

```bash
azd auth login
azd env new lab667-dev
azd up
```

For browserless Codespaces authentication, use
`azd auth login --use-device-code`. Signing in with `az login` alone does not
replace the azd login.

Select your subscription and a region supporting Container Apps and the model.
`azd up` provisions the resources, builds the four existing Dockerfiles, pushes
their images, and deploys the applications. You do not need to copy storage,
Maps, registry, or model keys into local files: Bicep supplies them as Container
Apps secrets. Deployment outputs contain URLs and resource names, not keys.

Provisioning initially uses a temporary Microsoft sample container listening
on each service's target port. `azd deploy` replaces it with the real image.
`azd provision` alone is therefore not a running workshop on the first run.
Keep the ignored `.azure/` environment directory: azd saves published image
references there so later provisioning reuses the application images.

### Model settings

Set overrides before `azd up`, or before a later `azd provision`:

| azd environment setting | Default |
| --- | --- |
| `AGENT42_MODEL_LOCATION` | Same as `AZURE_LOCATION` |
| `AGENT42_MODEL_NAME` | `gpt-5.6-luna` |
| `AGENT42_MODEL_VERSION` | `2026-07-09` |
| `AGENT42_MODEL_SKU` | `GlobalStandard` |
| `AGENT42_MODEL_CAPACITY` | `10` capacity units |

For example, to change the capacity:

```bash
azd env set AGENT42_MODEL_CAPACITY 20
```

Capacity units are model/SKU-specific; check your quota rather than assuming
that the value is requests per second. To place the model in a different
supported region, use `azd env set AGENT42_MODEL_LOCATION <region>`.
An unavailable model, incompatible version/SKU, or insufficient quota causes
provisioning to fail; the template does not silently substitute another model.

### Get endpoints and verify the deployment

```bash
azd env get-value GAME_MCP_URL
azd env get-value DASHBOARD_URL
azd env get-value ADMIN_URL
azd env get-value AGENT42_URL
```

1. Open `DASHBOARD_URL` and confirm it shows **Lost in San Francisco**.
2. Open `ADMIN_URL`, sign in with `admin` / `admin`, and complete the mandatory
   password change (12-128 characters). Sign in again with the new password and
   confirm the seeded game and quests are present. Subsequent deployments
   preserve the stored credentials. HTTPS-only session cookies are enabled by
   `ADMIN_COOKIE_SECURE=true` in the template.
3. Open the URL from `azd env get-value AGENT42_CARD_URL`; its JSON should
   advertise the deployed HTTPS Agent42 URL, not localhost.
4. Set `GAME_MCP_URL` and `AGENT42_URL` in the player's local environment file.
   The attendee instructions still contain the old hosted URLs; use the
   deployment outputs when running your own environment.
5. With the player's separate model/search settings configured, start the
   [player agent](../src/agents/player/) and complete a movement mission.
   Confirm Agent42 returns accessible map/directions links and that the
   dashboard can display the route.

The MCP endpoint is a protocol endpoint, not a browser page. Use an MCP client
to verify its tools. The services need outbound access to Azure resources and
Agent42 also calls Open-Meteo.

### Update, troubleshoot, and remove

```bash
azd deploy                 # Rebuild and deploy all four applications
azd deploy agent42         # Rebuild and deploy just Agent42
azd provision              # Apply infrastructure or model-setting changes
```

Codespaces automatically cleans old local workshop deployment tags after
deployment and trims unused Docker build cache toward 1 GB. It retains the
newest tag per service/environment repository and images used by containers;
volumes and Azure registry images are untouched. See the
[cleanup policy and manual preview command](../scripts/README.md#keep-local-docker-storage-small).

When upgrading to the versioned story editor, apply provisioning to supply the
admin's Maps secret, then deploy **mcp**, **dashboard**, and **admin** together
during a maintenance window. Do not publish new versions until all three run
the version-aware code: old MCP revisions do not pin players to their original
stories. No new storage account is needed. Existing quests migrate atomically
to version 1 on first access; take a data backup before an upgrade.

New games start as unpublished drafts. Save and publish in **Edit game** before
letting players register. Existing players keep their assigned story version.
The admin's Maps control, like the public dashboard, receives a Maps key in the
browser; restrict access and monitor Maps usage.

Each app starts with one replica (0.5 vCPU, 1 GiB) and is capped at one replica.
This avoids losing Agent42's in-memory A2A tasks between replicas; it is not a
capacity guarantee for a full room. Measure workshop load before changing
replica counts. Resources and usage incur charges even when no attendee is
actively playing.

If provisioning fails, check the reported region, quota, permissions, or policy
error. If deployment fails, inspect the Container App's revision and console
logs in the Azure portal. If only route animation fails, check that the public
`agent42-routes` container exists and matches the dashboard route base URL.

When the workshop environment is no longer needed:

```bash
azd down
```

This deletes the environment's Azure resources, including player progress,
quests, route blobs, and the dedicated model account. Back up anything needed
before confirming deletion.

## Legacy deployment workflows

[legacy-workflows/](legacy-workflows/) preserves the old workshop's workflows:

- [Game server](legacy-workflows/game-server.yml): builds the MCP, dashboard,
  and admin images.
- [Agent42](legacy-workflows/agent42.yml): builds the transport specialist image.
- [Workshop mirror](legacy-workflows/mirror-workshop.yml): publishes attendee
  instructions to the original external repository.
- [Workshop website](legacy-workflows/skillable-docs.yml): publishes attendee
  instructions to Azure Static Web Apps.

These files are deliberately **inactive** outside the root `.github/workflows/`
folder. Local source paths have been updated, but the old Azure resource names,
secrets, and publishing destinations have not. Review those settings before
enabling any workflow; this reorganization does not deploy or publish anything.

Dockerfiles and Compose configuration stay alongside each service in
[src/services/](../src/services/). See the
[game-server README](../src/services/game-server/README.md) for runtime settings.
