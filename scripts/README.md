# Workshop utilities

Run these commands from the repository root.

## Keep local Docker storage small

```bash
bash scripts/clean-local-docker.sh           # Preview only
bash scripts/clean-local-docker.sh --apply   # Remove old tags and trim cache
bash scripts/clean-local-docker.sh --apply --all-deployment-images
```

The [cleanup script](clean-local-docker.sh) retains the newest timestamped
`azd-deploy-*` image tag per workshop service/environment repository, including
registry-prefixed tags. It skips images referenced by any local container,
including stopped containers. Other project images and nondeployment tags
(such as `latest`) are not removed. No force-removal or volume cleanup is used.
It refuses nonlocal Docker endpoints.

The `--all-deployment-images` option is intended for use immediately before an
Azure Developer CLI deployment. It removes every unused workshop
`azd-deploy-*` tag and the four local `lost-in-san-francisco-*:latest` build
tags. Those images have already been pushed to Azure and are rebuilt by the
deployment, so removing them prevents old and new copies from consuming disk
at the same time. It still protects images referenced by containers and does
not touch unrelated images.

Unused cache in Docker's default builder is trimmed toward **1 GB**. This cache
is shared across projects; subsequent builds may need to download/rebuild layers.
Active and image-shared layers can keep actual usage above that target.
Do not run cleanup concurrently with builds/deployments.

In Codespaces, the root `predeploy` and `postdeploy` hooks in
[azure.yaml](../azure.yaml) run this automatically around deployment, including
the deploy phase of `azd up`. The pre-deploy pass removes existing unused
workshop deployment images to create maximum build headroom; the post-deploy
pass retains the newest deployment image per service and trims the newly
generated cache. Cleanup errors are reported without failing an otherwise
successful deployment. Outside Codespaces, cleanup is manual.
Requires Bash, jq, and Docker Buildx with `--max-used-space` support. Azure
registry images and deployed resources are unaffected.

## Restore azd images on fresh CI runners

[restore-azd-images.sh](restore-azd-images.sh) reads the deployed images from the
four shared Container Apps and writes their `SERVICE_*_IMAGE_NAME` values to the
active azd environment. The [deployment workflow](../.github/workflows/deploy.yml)
runs it before provisioning so existing images are not replaced by bootstrap
containers. It requires Azure CLI authentication, jq, and an initialized azd
environment matching `AZURE_ENV_NAME`. It does not modify Azure resources.

Run its isolated tests without Azure credentials:

```bash
bash scripts/test-restore-azd-images.sh
```

## Generate attendee indexes

```bash
python scripts/sync-to-skillable.py
```

The generator reads only numbered step files in
[player/guided/](../player/guided/) and writes
[skillable.md](../player/skillable.md) and [index.html](../player/index.html)
under [player/](../player/). It excludes the folder README.
The original Skillable hosting URLs are preserved; this command writes local
files only and does not publish them.

## Local game-server load test

[load_test.py](load_test.py) sends concurrent HTTP requests to a game server
at `http://127.0.0.1:8000`. Run it only against an instance intended for load
testing:

```bash
python scripts/load_test.py
```
